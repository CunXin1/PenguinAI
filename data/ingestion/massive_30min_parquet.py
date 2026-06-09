"""Massive 30-minute bars → per-symbol parquet under ``data/30min_data/``.

Adaptation of massive_minute_parquet.py for 30-minute bars. Downloads ~5 years
of 30-min OHLCV for the top ~50 symbols and writes one parquet per symbol using
the same 13-column BASE schema.

RUN (repo root; needs MASSIVE_API_KEY in .env):
    python -m data.ingestion.massive_30min_parquet --dry-run
    python -m data.ingestion.massive_30min_parquet --symbols AAPL SPY
    python -m data.ingestion.massive_30min_parquet          # full universe, 5yr

RESUMABLE: skips symbols whose parquet already exists (use --reset to overwrite).
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

logger = logging.getLogger("massive_30min_parquet")

ET = ZoneInfo("America/New_York")
_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _REPO / "30min_data"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_PAGE_LIMIT = 50_000


class LoaderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"


class _RateLimiter:
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
    if not api_key or "apiKey=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}apiKey={api_key}"


async def _get_json(
    client: httpx.AsyncClient, url: str, limiter: _RateLimiter, *, max_retries: int = 6
) -> dict | None:
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

TOP50 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "BRK.B", "JPM",
    "LLY", "V", "UNH", "MA", "COST", "HD", "NFLX", "PG", "JNJ", "CRM",
    "ABBV", "AMD", "BAC", "ORCL", "MRK", "PEP", "KO", "ADBE", "WMT", "TMO",
    "CSCO", "ACN", "INTC", "QCOM", "INTU", "AMGN", "AMAT", "ISRG", "GS", "NOW",
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "XLF", "XLK", "ARKK",
]


def _safe(symbol: str) -> str:
    return _SAFE.sub("_", symbol)


def _classify_asset(symbol: str) -> str:
    etfs = {"SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "XLF", "XLK", "ARKK",
            "IVV", "VUG", "VEA", "VTV", "IEFA", "BND", "AGG", "IWF", "IJH", "IEMG",
            "VWO", "IJR", "VIG", "VXUS"}
    return "etf" if symbol in etfs else "stock"


async def _fetch_series(
    client: httpx.AsyncClient, limiter: _RateLimiter, base: str, key: str,
    ticker: str, date_from: str, date_to: str, *, adjusted: bool,
) -> dict[int, tuple]:
    adj = "true" if adjusted else "false"
    url: str | None = _with_key(
        f"{base}/v2/aggs/ticker/{ticker}/range/30/minute/{date_from}/{date_to}"
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
            out[int(t)] = (o, h, low, c, int(round(float(r.get("v") or 0))))
        nxt = data.get("next_url")
        url = _with_key(nxt, key) if nxt else None
    return out


def _build_table(symbol: str, raw: dict[int, tuple], adj: dict[int, tuple]) -> pa.Table:
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
        cols["adj_volume"].append(r[4] if r else (a[4] if a else None))
    return pa.table(cols, schema=BASE_SCHEMA)


def _write_atomic(table: pa.Table, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(out)


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

    plan: list[tuple[str, str]] = [(sym, _classify_asset(sym)) for sym in symbols]

    if not reset:
        before = len(plan)
        plan = [(sym, a) for sym, a in plan if not (out_dir / a / f"{_safe(sym)}.parquet").exists()]
        if before - len(plan):
            logger.info("skipping %d symbols already written (use --reset to overwrite)", before - len(plan))

    logger.info(
        "30min parquet | %s..%s | symbols=%d (stock=%d etf=%d) | out=%s | conc=%d rate=%s",
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
                except Exception as exc:
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
    p = argparse.ArgumentParser(description="Backfill Massive 30-min bars → data/30min_data/ parquet.")
    p.add_argument("--symbols", nargs="*", default=None, help="Override the Top-50 list.")
    p.add_argument("--limit", type=int, default=None, help="Cap to the first N symbols.")
    p.add_argument("--years", type=int, default=5, help="History length (default 5).")
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
    symbols = [s.upper() for s in (args.symbols or TOP50)]
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
