"""Fetch recent 30-min bars from Yahoo Finance to bring every symbol up to the
latest date, then merge into the dataset. A no-login alternative to ibkr_fetch.py.

WHY: stock ADJ stops 2026-04-13 / RAW 2026-05-19, ETFs stop 2026-04-14. Yahoo
gives free 30-min bars but ONLY for the last ~60 calendar days (hard limit), which
currently covers both gaps (stock ~16d, etf ~51d) -- so run it SOON.

Behavior confirmed live against yfinance 1.4.1:
  * yf.download(auto_adjust=False) -> Open/High/Low/Close = unadjusted (raw_*),
    plus 'Adj Close' = split+div adjusted. adj_* reconstructed via factor=AdjClose/Close.
  * index is tz-aware America/New_York; ts=UTC, et_time=naive ET (matches the build).
  * prepost=True keeps 04:00-20:00 bars (matches useRTH=0 in the existing data).
  * Volume is real shares (no IBKR lot x100 issue).

Pulls a single uniform recent window (--period, default 58d, under the 60d cap) for
every symbol in batches (fast, threaded), stages per-symbol parquet, and the merge
dedups by ts against the existing files -- so the overlap is harmless.

STAGES (same as ibkr_fetch):
  fetch   -> ibkr_staging-style <staging>/<asset>/<SYMBOL>.parquet (13 BASE columns)
  --merge -> dedup into by_symbol by ts (BASE cols only); rerun compute_indicators.py.

Yahoo symbol quirk: class/preferred tickers use '-' not '.' (BRK.B -> BRK-B). We map
'.'->'-' for the query and keep the original symbol in the output. Failures (delisted/
unknown) are logged to the checkpoint for review.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_by_symbol import safe_filename
from ibkr_fetch import BASE_SCHEMA, existing_last_ts, load_symbols, run_merge

UTC = UTC


# --------------------------------------------------------------------------- conversion
def frame_to_table(df_t: pd.DataFrame, symbol: str) -> pa.Table | None:
    """One ticker's Yahoo OHLC frame (ET tz index) -> the 13-column BASE schema."""
    df_t = df_t.dropna(subset=["Close"])
    if df_t.empty:
        return None
    idx = df_t.index
    if idx.tz is None:
        idx = idx.tz_localize("America/New_York")
    ts_utc = idx.tz_convert("UTC")
    et_naive = idx.tz_convert("America/New_York").tz_localize(None)

    o = df_t["Open"].to_numpy("float64")
    h = df_t["High"].to_numpy("float64")
    low = df_t["Low"].to_numpy("float64")
    c = df_t["Close"].to_numpy("float64")
    adjc = (df_t["Adj Close"] if "Adj Close" in df_t.columns else df_t["Close"]).to_numpy("float64")
    vol = df_t["Volume"].fillna(0).to_numpy("float64").round().astype("int64")
    factor = np.where(c != 0.0, adjc / c, 1.0)

    out = pd.DataFrame(
        {
            "ts": pd.Series(ts_utc),
            "et_time": pd.Series(et_naive),
            "symbol": symbol,
            "raw_open": o,
            "raw_high": h,
            "raw_low": low,
            "raw_close": c,
            "raw_volume": vol,
            "adj_open": o * factor,
            "adj_high": h * factor,
            "adj_low": low * factor,
            "adj_close": adjc,
            "adj_volume": vol,
        }
    )
    return pa.Table.from_pandas(out, preserve_index=False).cast(BASE_SCHEMA)


def extract_ticker(data: pd.DataFrame, ysym: str) -> pd.DataFrame | None:
    """Pull one ticker's sub-frame out of a (multi-ticker) yf.download result."""
    if isinstance(data.columns, pd.MultiIndex):
        lvl0 = set(data.columns.get_level_values(0))
        if ysym in lvl0:  # group_by='ticker' -> (ticker, field)
            return data[ysym]
        lvl1 = set(data.columns.get_level_values(1))
        if ysym in lvl1:  # (field, ticker)
            return data.xs(ysym, axis=1, level=1)
        return None
    return data  # single-ticker, flat columns


# --------------------------------------------------------------------------- args
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch recent Yahoo 30-min bars and stage/merge them.")
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--staging-dir", default=r"D:\BaiduNetdiskDownload\30min\yahoo_staging")
    p.add_argument("--asset-type", choices=["stock", "etf", "all"], default="all")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--interval", default="30m")
    p.add_argument("--period", default="58d", help="Uniform recent window (Yahoo 30m cap = 60d).")
    p.add_argument("--prepost", type=int, choices=[0, 1], default=1)
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--sleep-between", type=float, default=1.0, help="Seconds between batches.")
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--checkpoint", default=None, help="Defaults to <staging>/_checkpoint.jsonl")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--merge", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


# --------------------------------------------------------------------------- fetch
def run_fetch(args, plan, checkpoint_path: Path, done: set[str]) -> int:
    import yfinance as yf

    staging = Path(args.staging_dir)
    window_start = datetime.now(UTC) - timedelta(days=int(str(args.period).rstrip("d") or 58))

    todo = [
        (sym, at, src) for (sym, at, src) in plan if not (args.resume and f"{at}/{sym}" in done)
    ]

    # map original ticker -> yahoo ticker: class/preferred shares use '-' not '.',
    # and undo the reserved-name suffix (PRN -> PRN_ at export time) so PRN_ queries PRN.
    from export_by_symbol import _RESERVED

    def to_yahoo(sym: str) -> str:
        y = sym[:-1] if sym.endswith("_") and sym[:-1].upper() in _RESERVED else sym
        return y.replace(".", "-")

    ymap = {sym: to_yahoo(sym) for (sym, _, _) in todo}

    ok = empty = failed = residual = 0
    started = time.time()
    n_batches = (len(todo) + args.batch_size - 1) // args.batch_size

    for b in range(n_batches):
        batch = todo[b * args.batch_size : (b + 1) * args.batch_size]
        ytickers = [ymap[sym] for (sym, _, _) in batch]

        data = None
        for attempt in range(1, args.max_retries + 1):
            try:
                data = yf.download(
                    ytickers,
                    period=args.period,
                    interval=args.interval,
                    auto_adjust=False,
                    prepost=bool(args.prepost),
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
                if data is not None and not data.empty:
                    break
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  [batch {b + 1}] attempt {attempt} error: {exc}", file=sys.stderr, flush=True
                )
            time.sleep(args.sleep_between * attempt * 2)

        for sym, at, src in batch:
            key = f"{at}/{sym}"
            try:
                sub = extract_ticker(data, ymap[sym]) if data is not None else None
                table = frame_to_table(sub, sym) if sub is not None else None
                if table is None or table.num_rows == 0:
                    empty += 1
                    rec = {"key": key, "rows": 0, "note": "no data (delisted/unknown/symbol-map?)"}
                else:
                    out = staging / at / f"{safe_filename(sym)}.parquet"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    tmp = out.with_suffix(".parquet.tmp")
                    pq.write_table(table, tmp, compression="zstd")
                    tmp.replace(out)
                    ok += 1
                    last = existing_last_ts(src)
                    gap_covered = (last is None) or (last >= window_start - timedelta(days=1))
                    if not gap_covered:
                        residual += 1
                    rec = {
                        "key": key,
                        "rows": table.num_rows,
                        "first": str(table.column("ts")[0]),
                        "last": str(table.column("ts")[-1]),
                        "prev_last": str(last),
                        "residual_gap": not gap_covered,
                    }
            except Exception as exc:  # noqa: BLE001
                failed += 1
                rec = {"key": key, "error": repr(exc)}
                print(f"  ERR {key}: {exc}", file=sys.stderr, flush=True)
            with checkpoint_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

        print(
            f"  batch {b + 1}/{n_batches} ok={ok} empty={empty} fail={failed} "
            f"residual_gap={residual} elapsed={time.time() - started:,.0f}s",
            file=sys.stderr,
            flush=True,
        )
        if b < n_batches - 1:
            time.sleep(args.sleep_between)

    print(f"fetch done: ok={ok} empty={empty} failed={failed} residual_gap(>window)={residual}")
    if residual:
        print(
            f"  NOTE: {residual} symbols last bar is older than the {args.period} window "
            f"-> Yahoo 30m can't reach it; they keep a residual gap."
        )
    return 0 if failed == 0 else 1


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
                if not rec.get("error") and rec.get("rows", 0) > 0:
                    done.add(rec["key"])
            except Exception:  # noqa: BLE001
                pass

    print(
        f"plan: {len(plan):,} symbols | interval={args.interval} period={args.period} "
        f"prepost={args.prepost} batch={args.batch_size} | resume skip={len(done):,}"
    )
    if args.dry_run:
        for sym, at, src in plan[:10]:
            print(f"  {at}/{sym} (yahoo='{sym.replace('.', '-')}') last={existing_last_ts(src)}")
        if len(plan) > 10:
            print(f"  ... (+{len(plan) - 10:,} more)")
        print("dry-run: no fetch, nothing written.")
        return 0

    staging.mkdir(parents=True, exist_ok=True)
    rc = run_fetch(args, plan, checkpoint_path, done)
    if args.merge:
        rc = run_merge(args, plan) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
