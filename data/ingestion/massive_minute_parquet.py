"""Massive 1-minute bars → per-symbol parquet under ``data/minute_data/``.

WHAT: backfills ~2 years of 1-minute bars for the Nasdaq-100 + Top-20 ETF
universe from the Massive REST API and writes one parquet per symbol,
**schema-identical to the
raw IBKR staging files** produced by ``backend/scripts/market_data/ibkr_fetch.py``
(the 13-column BASE schema: ts/et_time/symbol/raw_*/adj_*). Indicators are NOT
computed here — run the existing ``compute_indicators.py`` downstream, exactly as
for the 30-min data.

WHY: real-time display uses IBKR; this is the *offline* minute history. It lands
as files under ``data/`` (the source of truth), mirroring ``data/30min_data/`` —
NOT in TimescaleDB. Layout: ``data/minute_data/<asset>/<SYMBOL>.parquet`` where
``<asset>`` (stock|etf) is taken from where the symbol's 30-min file already lives.

SCHEMA (mirrors ibkr_fetch.BASE_SCHEMA exactly so the same pipeline consumes it):
    ts          timestamp[us, tz=UTC]   bar open time, UTC
    et_time     timestamp[us]           same instant as naive America/New_York wall-clock
    symbol      string
    raw_open/high/low/close   float64   UNADJUSTED  (Massive adjusted=false)
    raw_volume                int64
    adj_open/high/low/close   float64   ADJUSTED    (Massive adjusted=true)
    adj_volume                int64     = raw_volume when present, else adjusted's
Two Massive calls per symbol (adjusted=false → raw_*, adjusted=true → adj_*),
merged on the millisecond timestamp — the same TRADES/ADJUSTED_LAST split IBKR uses.

CAVEAT: Massive ``adjusted=true`` is split-adjusted (Polygon-style); IBKR
ADJUSTED_LAST is split+dividend. Close enough for the schema, but adj_* here is
split-only — recompute true adjusted downstream if you need dividend adjustment.
Massive also returns vwap/n, dropped here for exact schema parity (easy to add).

RUN (repo root; needs MASSIVE_API_KEY in .env; uses the backend venv which has
httpx + pyarrow):
    backend/.venv/Scripts/python -m data.ingestion.massive_minute_parquet --dry-run
    backend/.venv/Scripts/python -m data.ingestion.massive_minute_parquet --symbols AAPL SPY
    backend/.venv/Scripts/python -m data.ingestion.massive_minute_parquet          # full Top-100, 2yr

RESUMABLE: skips symbols whose parquet already exists (use --reset to overwrite).
Writes atomically (.tmp → replace), so a killed run never leaves a corrupt file.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("massive_minute_parquet")

ET = ZoneInfo("America/New_York")
_REPO = Path(__file__).resolve().parents[1]
_THIRTYMIN_ROOT = _REPO / "30min_data"  # data/30min_data/{stock,etf} — universe + asset type
_DEFAULT_OUT = _REPO / "minute_data"  # data/minute_data/{stock,etf}/<SYM>.parquet
_SAFE = re.compile(r"[^A-Za-z0-9._-]")  # mirrors export_by_symbol.safe_filename
_PAGE_LIMIT = 50_000  # Massive max aggregates per page


# ── Massive REST settings + HTTP layer (self-contained) ──────────────────────
class LoaderSettings(BaseSettings):
    """Env-backed Massive credentials (reads the repo-root .env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"


class _RateLimiter:
    """Min-interval limiter shared across concurrent workers (0 = unlimited)."""

    def __init__(self, rate_per_sec: float) -> None:
        self._interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next > now:
                await asyncio.sleep(self._next - now)
                now = loop.time()
            self._next = max(now, self._next) + self._interval


def _with_key(url: str, api_key: str) -> str:
    """Append ?apiKey= (Polygon-style) if absent — covers next_url, which omits it."""
    if not api_key or "apiKey=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}apiKey={api_key}"


async def _get_json(
    client: httpx.AsyncClient, url: str, limiter: _RateLimiter, *, max_retries: int = 6
) -> dict | None:
    """GET with retry/backoff on 429 + 5xx (honors Retry-After) and transport errors."""
    for attempt in range(max_retries + 1):
        await limiter.wait()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            if attempt == max_retries:
                raise
            logger.warning("transport error (%r) — retry %d", exc, attempt + 1)
            await asyncio.sleep(min(2**attempt, 30))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == max_retries:
                resp.raise_for_status()
            ra = resp.headers.get("Retry-After", "")
            delay = float(ra) if ra.replace(".", "", 1).isdigit() else min(2**attempt, 30)
            logger.warning("HTTP %d — backing off %.1fs", resp.status_code, delay)
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        return resp.json()
    return None


# 13-column BASE schema, identical to ibkr_fetch.BASE_SCHEMA (float64 prices).
BASE_COLUMNS = [
    "ts", "et_time", "symbol",
    "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
]
BASE_SCHEMA = pa.schema(
    [
        ("ts", pa.timestamp("us", tz="UTC")),
        ("et_time", pa.timestamp("us")),
        ("symbol", pa.string()),
        ("raw_open", pa.float64()), ("raw_high", pa.float64()),
        ("raw_low", pa.float64()), ("raw_close", pa.float64()),
        ("raw_volume", pa.int64()),
        ("adj_open", pa.float64()), ("adj_high", pa.float64()),
        ("adj_low", pa.float64()), ("adj_close", pa.float64()),
        ("adj_volume", pa.int64()),
    ]
)

# ── Universe: Nasdaq-100 constituents + Top-20 ETFs ───────────────────────────
# NASDAQ100 = current Nasdaq-100 index members (en.wikipedia.org/wiki/Nasdaq-100,
# fetched 2026-06-05). Edit here on index reconstitution. TOP20_ETF = the 20
# largest US-listed ETFs by AUM. Both are filtered at runtime to symbols that
# actually exist under data/30min_data/ (the source-of-truth universe).
NASDAQ100 = [
    "ADBE", "AMD", "ABNB", "ALNY", "GOOGL", "GOOG", "AMZN", "AEP", "AMGN", "ADI",
    "AAPL", "AMAT", "APP", "ARM", "ASML", "ADSK", "ADP", "AXON", "BKR", "BKNG",
    "AVGO", "CDNS", "CHTR", "CTAS", "CSCO", "CCEP", "CTSH", "CMCSA", "CEG", "CPRT",
    "COST", "CRWD", "CSX", "DDOG", "DXCM", "FANG", "DASH", "EA", "EXC", "FAST",
    "FER", "FTNT", "GEHC", "GILD", "HON", "IDXX", "INSM", "INTC", "INTU", "ISRG",
    "KDP", "KLAC", "KHC", "LRCX", "LIN", "LITE", "MAR", "MRVL", "MELI", "META",
    "MCHP", "MU", "MSFT", "MSTR", "MDLZ", "MPWR", "MNST", "NFLX", "NVDA", "NXPI",
    "ORLY", "ODFL", "PCAR", "PLTR", "PANW", "PAYX", "PYPL", "PDD", "PEP", "QCOM",
    "REGN", "ROP", "ROST", "SNDK", "STX", "SHOP", "SBUX", "SNPS", "TMUS", "TTWO",
    "TSLA", "TXN", "TRI", "VRSK", "VRTX", "WMT", "WBD", "WDC", "WDAY", "XEL", "ZS",
]
TOP20_ETF = [
    "SPY", "IVV", "VOO", "VTI", "QQQ", "VUG", "VEA", "VTV", "IEFA", "BND",
    "AGG", "IWF", "IJH", "IEMG", "GLD", "VWO", "IJR", "VIG", "IWM", "VXUS",
]
DEFAULT_UNIVERSE = NASDAQ100 + TOP20_ETF


def _safe(symbol: str) -> str:
    return _SAFE.sub("_", symbol)


def _resolve_asset(symbol: str) -> str | None:
    """stock|etf based on where the 30-min file lives, or None if not in the universe."""
    fn = f"{_safe(symbol)}.parquet"
    for asset in ("stock", "etf"):
        if (_THIRTYMIN_ROOT / asset / fn).exists():
            return asset
    return None


# ── Fetch ────────────────────────────────────────────────────────────────────
async def _fetch_series(
    client: httpx.AsyncClient, limiter: _RateLimiter, base: str, key: str,
    ticker: str, date_from: str, date_to: str, *, adjusted: bool,
) -> dict[int, tuple]:
    """{t_ms: (o, h, l, c, volume)} for 1-min bars over [from,to], paginated."""
    adj = "true" if adjusted else "false"
    url: str | None = _with_key(
        f"{base}/v2/aggs/ticker/{ticker}/range/1/minute/{date_from}/{date_to}"
        f"?adjusted={adj}&sort=asc&limit={_PAGE_LIMIT}",
        key,
    )
    out: dict[int, tuple] = {}
    while url:
        data = await _get_json(client, url, limiter)
        if not data:
            break
        for r in data.get("results") or []:
            t, o, h, low, c = r.get("t"), r.get("o"), r.get("h"), r.get("l"), r.get("c")
            if t is None or None in (o, h, low, c):
                continue
            # Prices -> 4 dp (standardized precision; matches compute_indicators.py + DB).
            out[int(t)] = (
                round(float(o), 4), round(float(h), 4), round(float(low), 4),
                round(float(c), 4), int(round(float(r.get("v") or 0))),
            )
        nxt = data.get("next_url")
        url = _with_key(nxt, key) if nxt else None
    return out


def _build_table(symbol: str, raw: dict[int, tuple], adj: dict[int, tuple]) -> pa.Table:
    """Merge raw (TRADES) + adj (ADJUSTED) on ts into the 13-column BASE schema."""
    all_t = sorted(set(raw) | set(adj))
    cols: dict[str, list] = {c: [] for c in BASE_COLUMNS}
    for t in all_t:
        ts = datetime.fromtimestamp(t / 1000.0, tz=UTC)
        r = raw.get(t)
        a = adj.get(t)
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
        # raw_volume == adj_volume convention; fall back to adjusted's own if no raw
        cols["adj_volume"].append(r[4] if r else (a[4] if a else None))
    return pa.table(cols, schema=BASE_SCHEMA)


def _write_atomic(table: pa.Table, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(out)


# ── Run ──────────────────────────────────────────────────────────────────────
async def _load_symbol(
    client, limiter, base, key, symbol, asset, date_from, date_to, out_dir,
) -> int:
    raw = await _fetch_series(client, limiter, base, key, symbol, date_from, date_to, adjusted=False)
    adj = await _fetch_series(client, limiter, base, key, symbol, date_from, date_to, adjusted=True)
    if not raw and not adj:
        logger.warning("%s: no bars returned — skipping", symbol)
        return 0
    table = _build_table(symbol, raw, adj)
    _write_atomic(table, out_dir / asset / f"{_safe(symbol)}.parquet")
    return table.num_rows


async def run(
    symbols: list[str], date_from: str, date_to: str, out_dir: Path,
    *, concurrency: int, rate: float, timeout: float, reset: bool, dry_run: bool,
) -> None:
    s = LoaderSettings()
    if not s.MASSIVE_API_KEY:
        logger.error("MASSIVE_API_KEY is empty — set it in .env")
        return

    # Resolve universe → (symbol, asset); warn on symbols missing from data/30min_data.
    plan: list[tuple[str, str]] = []
    missing: list[str] = []
    for sym in symbols:
        asset = _resolve_asset(sym)
        (plan.append((sym, asset)) if asset else missing.append(sym))
    if missing:
        logger.warning("not in data/30min_data universe, skipped: %s", ", ".join(missing))

    if not reset:
        before = len(plan)
        plan = [(sym, a) for sym, a in plan if not (out_dir / a / f"{_safe(sym)}.parquet").exists()]
        if before - len(plan):
            logger.info("skipping %d symbols already written (use --reset to overwrite)", before - len(plan))

    logger.info(
        "minute parquet | %s..%s | symbols=%d (stock=%d etf=%d) | out=%s | conc=%d rate=%s",
        date_from, date_to, len(plan),
        sum(a == "stock" for _, a in plan), sum(a == "etf" for _, a in plan),
        out_dir, concurrency, rate or "inf",
    )
    if dry_run:
        logger.info("dry-run — plan: %s", ", ".join(f"{sym}({a})" for sym, a in plan[:30]))
        return
    if not plan:
        logger.info("nothing to do")
        return

    limiter = _RateLimiter(rate)
    sem = asyncio.Semaphore(concurrency)
    counters = {"done": 0, "rows": 0}

    async with httpx.AsyncClient(
        timeout=timeout, headers={"Authorization": f"Bearer {s.MASSIVE_API_KEY}"}
    ) as client:

        async def worker(sym: str, asset: str) -> None:
            async with sem:
                try:
                    n = await _load_symbol(
                        client, limiter, s.MASSIVE_BASE_URL, s.MASSIVE_API_KEY,
                        sym, asset, date_from, date_to, out_dir,
                    )
                except Exception as exc:  # noqa: BLE001 — skip + keep going, re-run retries
                    logger.error("FAILED %s: %r", sym, exc)
                    return
            counters["done"] += 1
            counters["rows"] += n
            logger.info("[%d/%d] %s (%s): %d bars", counters["done"], len(plan), sym, asset, n)

        await asyncio.gather(*(worker(sym, a) for sym, a in plan))

    logger.info("DONE — %d symbols, %d bars → %s", counters["done"], counters["rows"], out_dir)


def _years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill Massive 1-min bars → data/minute_data/ parquet.")
    p.add_argument("--symbols", nargs="*", default=None, help="Override the Top-100 list.")
    p.add_argument("--limit", type=int, default=None, help="Cap to the first N symbols.")
    p.add_argument("--years", type=int, default=2, help="History length (default 2).")
    p.add_argument("--from", dest="date_from", default=None, help="Start YYYY-MM-DD (ET).")
    p.add_argument("--to", dest="date_to", default=None, help="End YYYY-MM-DD (ET).")
    p.add_argument("--out-dir", default=str(_DEFAULT_OUT))
    p.add_argument("--concurrency", type=int, default=4, help="Concurrent symbols in flight.")
    p.add_argument("--rate", type=float, default=0.0, help="Max requests/sec (0 = unlimited).")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--reset", action="store_true", help="Overwrite existing parquet files.")
    p.add_argument("--dry-run", action="store_true", help="Print the plan and exit (no API calls).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    today = datetime.now(ET).date()
    date_from = args.date_from or _years_ago(today, args.years).isoformat()
    date_to = args.date_to or today.isoformat()
    symbols = [s.upper() for s in (args.symbols or DEFAULT_UNIVERSE)]
    if args.limit:
        symbols = symbols[: args.limit]
    try:
        asyncio.run(
            run(
                symbols, date_from, date_to, Path(args.out_dir),
                concurrency=args.concurrency, rate=args.rate, timeout=args.timeout,
                reset=args.reset, dry_run=args.dry_run,
            )
        )
    except KeyboardInterrupt:
        logger.info("interrupted — re-run to resume (already-written symbols are skipped)")


if __name__ == "__main__":
    main()
