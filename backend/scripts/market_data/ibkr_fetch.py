"""Fetch recent bars from Interactive Brokers and merge them into the dataset.

WHY: the bundled stock ADJ series stops 2026-04-13 while RAW runs to 2026-05-19
(an export-vintage gap), and ETFs stop 2026-04-13. This pulls fresh bars from
IBKR to bring every symbol up to the latest and keep raw + adjusted aligned.

HOW IBKR works here (researched against the TWS API docs):
  * Requires TWS or IB Gateway running locally with the API enabled.
      TWS:  7496 live / 7497 paper.   Gateway: 4001 live / 4002 paper.
  * Two requests per symbol per timeframe give us both price series:
      whatToShow='TRADES'         -> unadjusted  -> raw_*
      whatToShow='ADJUSTED_LAST'  -> split+div adjusted -> adj_*
  * useRTH=0 keeps pre/post bars so the schema matches the existing 04:00-20:00 data.
  * formatDate=2 returns UTC; we derive ET wall-clock with zoneinfo (as the build does).
  * PACING (hard, unavoidable): <=60 historical requests / 10 min, no identical
    request within 15s, <=6 per contract within 2s. 6,454 symbols x2 = ~12,908
    requests ~= 1.5 days for 30-min. So: rate-limited + checkpointed + resumable.

This script CANNOT be tested without a live Gateway/TWS + your market-data
subscriptions. Use --dry-run (offline) to see the plan first, then run a tiny
--symbols AAPL SPY against your Gateway before the full universe.

STAGES:
  1. fetch    -> writes per-symbol bars to <staging>/<asset>/<SYMBOL>.parquet
                 (schema = the 13 base columns; indicators are NOT recomputed here)
  2. --merge  -> dedups staging into by_symbol/<asset>/<SYMBOL>.parquet by ts.
                 Writes BASE columns only; rerun compute_indicators.py afterwards.

VOLUME CAVEAT: IBKR historical stock volume has historically been reported in
lots (x100 shares). Use --volume-scale and the overlap rows (--gap-extra-days)
to calibrate against the existing data before trusting merged volume.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_by_symbol import safe_filename

ET = ZoneInfo("America/New_York")
UTC = UTC

BASE_COLUMNS = [
    "ts",
    "et_time",
    "symbol",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
]
BASE_SCHEMA = pa.schema(
    [
        ("ts", pa.timestamp("us", tz="UTC")),
        ("et_time", pa.timestamp("us")),
        ("symbol", pa.string()),
        ("raw_open", pa.float64()),
        ("raw_high", pa.float64()),
        ("raw_low", pa.float64()),
        ("raw_close", pa.float64()),
        ("raw_volume", pa.int64()),
        ("adj_open", pa.float64()),
        ("adj_high", pa.float64()),
        ("adj_low", pa.float64()),
        ("adj_close", pa.float64()),
        ("adj_volume", pa.int64()),
    ]
)

BAR_SIZES = {"30min": "30 mins", "1min": "1 min", "1day": "1 day"}


# --------------------------------------------------------------------------- rate limiter
class RateLimiter:
    """Keep historical requests under IBKR's 60-per-10-min ceiling (with margin)."""

    def __init__(self, max_in_window: int, window_sec: float, min_interval_sec: float):
        self.max_in_window = max_in_window
        self.window_sec = window_sec
        self.min_interval = min_interval_sec
        self._stamps: deque[float] = deque()
        self._last = 0.0

    def acquire(self) -> None:
        now = time.monotonic()
        # enforce a minimum gap between consecutive requests
        wait = self.min_interval - (now - self._last)
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        # enforce the sliding-window ceiling
        while self._stamps and now - self._stamps[0] > self.window_sec:
            self._stamps.popleft()
        if len(self._stamps) >= self.max_in_window:
            sleep_for = self.window_sec - (now - self._stamps[0]) + 0.5
            print(
                f"  [rate] window full ({len(self._stamps)}), sleeping {sleep_for:,.0f}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(max(0.0, sleep_for))
            now = time.monotonic()
            while self._stamps and now - self._stamps[0] > self.window_sec:
                self._stamps.popleft()
        self._stamps.append(now)
        self._last = now


# --------------------------------------------------------------------------- helpers
def to_utc(bar_date) -> datetime:
    """Normalize a BarData.date (formatDate=2 -> UTC datetime or epoch int) to UTC."""
    if isinstance(bar_date, (int, float)):
        return datetime.fromtimestamp(bar_date, tz=UTC)
    if isinstance(bar_date, datetime):
        return bar_date.astimezone(UTC) if bar_date.tzinfo else bar_date.replace(tzinfo=UTC)
    # date (daily bars): treat as ET session date at 00:00
    return datetime(bar_date.year, bar_date.month, bar_date.day, tzinfo=ET).astimezone(UTC)


def bars_to_map(bars, volume_scale: float) -> dict[datetime, tuple]:
    """ts(UTC) -> (open, high, low, close, volume)."""
    out = {}
    for b in bars:
        ts = to_utc(b.date)
        vol = int(round((b.volume or 0) * volume_scale)) if b.volume and b.volume > 0 else 0
        out[ts] = (b.open, b.high, b.low, b.close, vol)
    return out


def merge_trades_adjusted(trades: dict, adjusted: dict, symbol: str) -> pa.Table:
    """Combine TRADES (raw_*) and ADJUSTED_LAST (adj_*) on ts into the wide schema."""
    all_ts = sorted(set(trades) | set(adjusted))
    cols = {c: [] for c in BASE_COLUMNS}
    for ts in all_ts:
        r = trades.get(ts)
        a = adjusted.get(ts)
        cols["ts"].append(ts)
        cols["et_time"].append(ts.astimezone(ET).replace(tzinfo=None))
        cols["symbol"].append(symbol)
        cols["raw_open"].append(r[0] if r else None)
        cols["raw_high"].append(r[1] if r else None)
        cols["raw_low"].append(r[2] if r else None)
        cols["raw_close"].append(r[3] if r else None)
        cols["raw_volume"].append(r[4] if r else None)
        cols["adj_open"].append(a[0] if a else None)
        cols["adj_high"].append(a[1] if a else None)
        cols["adj_low"].append(a[2] if a else None)
        cols["adj_close"].append(a[3] if a else None)
        # keep raw_volume == adj_volume convention; fall back to adjusted's own if no raw
        cols["adj_volume"].append(r[4] if r else (a[4] if a else None))
    return pa.table(cols, schema=BASE_SCHEMA)


def existing_last_ts(path: Path) -> datetime | None:
    if not path.exists():
        return None
    t = pq.read_table(path, columns=["ts"])
    if t.num_rows == 0:
        return None
    return max(t.column("ts").to_pylist())


def duration_for_gap(
    last_ts: datetime | None, now: datetime, extra_days: int, full_duration: str
) -> str:
    if last_ts is None:
        return full_duration
    days = (now - last_ts).days + extra_days + 1
    return f"{max(1, days)} D"


# --------------------------------------------------------------------------- planning
def load_symbols(
    by_symbol_root: Path, asset_types: list[str], only: set[str] | None, limit: int | None
) -> list[tuple[str, str, Path]]:
    plan = []
    for at in asset_types:
        d = by_symbol_root / at
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.parquet")):
            sym = f.stem
            if only is not None and sym.upper() not in only:
                continue
            plan.append((sym, at, f))
    if limit:
        plan = plan[:limit]
    return plan


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch recent IBKR bars and stage/merge them.")
    # connection
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7497, help="TWS 7496/7497, Gateway 4001/4002.")
    p.add_argument("--client-id", type=int, default=17)
    p.add_argument("--connect-timeout", type=float, default=20.0)
    # scope
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--staging-dir", default=r"D:\BaiduNetdiskDownload\30min\ibkr_staging")
    p.add_argument("--asset-type", choices=["stock", "etf", "all"], default="all")
    p.add_argument("--symbols", nargs="*", default=None, help="Subset of tickers (smoke test).")
    p.add_argument("--limit", type=int, default=None)
    # request shape
    p.add_argument("--timeframe", choices=list(BAR_SIZES), default="30min")
    p.add_argument("--what", choices=["both", "trades", "adjusted"], default="both")
    p.add_argument("--use-rth", type=int, choices=[0, 1], default=0)
    p.add_argument("--mode", choices=["gap", "full"], default="gap")
    p.add_argument("--gap-extra-days", type=int, default=5, help="Overlap buffer before last bar.")
    p.add_argument("--full-duration", default="30 Y")
    p.add_argument(
        "--volume-scale",
        type=float,
        default=1.0,
        help="Multiply IBKR volume (historically lots x100 for stocks). Calibrate first!",
    )
    p.add_argument("--req-timeout", type=float, default=60.0)
    # pacing
    p.add_argument("--max-req-per-window", type=int, default=55)
    p.add_argument("--window-sec", type=float, default=600.0)
    p.add_argument("--min-interval-sec", type=float, default=0.6)
    # control
    p.add_argument("--checkpoint", default=None, help="Defaults to <staging>/_checkpoint.jsonl")
    p.add_argument("--resume", action="store_true", help="Skip symbols already in the checkpoint.")
    p.add_argument(
        "--merge", action="store_true", help="After fetch, merge staging into by_symbol."
    )
    p.add_argument("--dry-run", action="store_true", help="Plan only; no connection, no writes.")
    return p.parse_args()


# --------------------------------------------------------------------------- fetch
def run_fetch(args, plan, checkpoint_path: Path, done: set[str]) -> int:
    from ib_async import IB, Stock  # imported lazily so --dry-run works offline

    bar_size = BAR_SIZES[args.timeframe]
    whats = {
        "both": ["TRADES", "ADJUSTED_LAST"],
        "trades": ["TRADES"],
        "adjusted": ["ADJUSTED_LAST"],
    }[args.what]
    staging = Path(args.staging_dir)
    limiter = RateLimiter(args.max_req_per_window, args.window_sec, args.min_interval_sec)
    now = datetime.now(UTC)

    ib = IB()
    print(f"connecting {args.host}:{args.port} clientId={args.client_id} ...", flush=True)
    ib.connect(
        args.host, args.port, clientId=args.client_id, timeout=args.connect_timeout, readonly=True
    )
    print("connected.", flush=True)

    ok = skipped = failed = 0
    started = time.time()
    try:
        for i, (sym, at, src) in enumerate(plan, start=1):
            key = f"{at}/{sym}"
            if args.resume and key in done:
                skipped += 1
                continue
            dur = (
                args.full_duration
                if args.mode == "full"
                else duration_for_gap(
                    existing_last_ts(src), now, args.gap_extra_days, args.full_duration
                )
            )
            contract = Stock(sym, "SMART", "USD")
            try:
                if not ib.qualifyContracts(contract):
                    raise RuntimeError("qualifyContracts returned nothing (unknown symbol?)")
                series = {}
                for w in whats:
                    limiter.acquire()
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime="",
                        durationStr=dur,
                        barSizeSetting=bar_size,
                        whatToShow=w,
                        useRTH=bool(args.use_rth),
                        formatDate=2,
                        keepUpToDate=False,
                        timeout=args.req_timeout,
                    )
                    series[w] = bars_to_map(
                        bars, args.volume_scale if w == "TRADES" else args.volume_scale
                    )
                trades = series.get("TRADES", {})
                adjusted = series.get("ADJUSTED_LAST", {})
                table = merge_trades_adjusted(trades, adjusted, sym)
                if table.num_rows == 0:
                    raise RuntimeError("no bars returned")
                out = staging / at / f"{safe_filename(sym)}.parquet"
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".parquet.tmp")
                pq.write_table(table, tmp, compression="zstd")
                tmp.replace(out)
                ok += 1
                rec = {
                    "key": key,
                    "rows": table.num_rows,
                    "duration": dur,
                    "first": str(min(trades or adjusted)),
                    "last": str(max(trades or adjusted)),
                }
            except Exception as exc:  # noqa: BLE001
                failed += 1
                rec = {"key": key, "error": repr(exc), "duration": dur}
                print(f"  ERR {key}: {exc}", file=sys.stderr, flush=True)
            with checkpoint_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            if i % 25 == 0 or i == len(plan):
                print(
                    f"  {i}/{len(plan)} ok={ok} skip={skipped} fail={failed} "
                    f"elapsed={time.time() - started:,.0f}s",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        ib.disconnect()
    print(f"fetch done: ok={ok} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------- merge
def run_merge(args, plan) -> int:
    staging = Path(args.staging_dir)
    merged = 0
    added_total = 0
    for sym, at, dst in plan:
        stg = staging / at / f"{safe_filename(sym)}.parquet"
        if not stg.exists():
            continue
        import pyarrow.compute as pc

        new = pq.read_table(stg).select(BASE_COLUMNS).cast(BASE_SCHEMA)
        if dst.exists():
            old = pq.read_table(dst)
            old = old.select([c for c in BASE_COLUMNS if c in old.column_names]).cast(BASE_SCHEMA)
            if old.num_rows:
                # append-only: keep all existing bars, add only strictly-newer ts (no overwrite)
                old_max = pc.max(old.column("ts")).as_py()
                new = new.filter(
                    pc.greater(new.column("ts"), pa.scalar(old_max, type=new.column("ts").type))
                )
            combined = pa.concat_tables([old, new])
        else:
            combined = new
        order = pc.sort_indices(combined, sort_keys=[("ts", "ascending")])
        combined = combined.take(order)
        tmp = dst.with_suffix(".parquet.tmp")
        pq.write_table(combined, tmp, compression="zstd")
        tmp.replace(dst)
        merged += 1
        added_total += new.num_rows
    print(
        f"merge done: {merged} files updated, {added_total:,} new bars appended (BASE cols; append-only)."
    )
    print("NEXT: rerun  python compute_indicators.py --scope all  to (re)derive indicators.")
    return 0


def main() -> int:
    args = parse_args()
    by_symbol_root = Path(args.by_symbol_root)
    asset_types = ["stock", "etf"] if args.asset_type == "all" else [args.asset_type]
    only = {s.upper() for s in args.symbols} if args.symbols else None
    plan = load_symbols(by_symbol_root, asset_types, only, args.limit)

    staging = Path(args.staging_dir)
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else staging / "_checkpoint.jsonl"
    done: set[str] = set()
    if args.resume and checkpoint_path.exists():
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if "error" not in rec:
                    done.add(rec["key"])
            except Exception:  # noqa: BLE001
                pass

    n_req = len(plan) * (2 if args.what == "both" else 1)
    est_min = n_req / args.max_req_per_window * (args.window_sec / 60.0)
    print(
        f"plan: {len(plan):,} symbols | timeframe={args.timeframe} what={args.what} "
        f"mode={args.mode} useRTH={args.use_rth}"
    )
    print(
        f"  ~{n_req:,} requests | rate {args.max_req_per_window}/{args.window_sec / 60:.0f}min "
        f"-> ~{est_min / 60:.1f}h | resume skip={len(done):,}"
    )
    if args.dry_run:
        for sym, at, src in plan[:10]:
            last = existing_last_ts(src) if args.mode == "gap" else None
            dur = (
                args.full_duration
                if args.mode == "full"
                else duration_for_gap(
                    last, datetime.now(UTC), args.gap_extra_days, args.full_duration
                )
            )
            print(f"  {at}/{sym}: last={last} -> durationStr='{dur}'")
        if len(plan) > 10:
            print(f"  ... (+{len(plan) - 10:,} more)")
        print("dry-run: no connection made, nothing written.")
        return 0

    staging.mkdir(parents=True, exist_ok=True)
    rc = run_fetch(args, plan, checkpoint_path, done)
    if args.merge:
        rc = run_merge(args, plan) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
