"""Massive (massive.com) → ``market_data_1min`` historical minute-bar loader.

WHAT: backfills 1-minute OHLCV bars for the US-equity universe from the Massive
REST API (a Polygon.io-compatible vendor) into the ``market_data_1min``
hypertable, and incrementally refreshes the most recent trading day after the
close. The FastAPI ``/api/market-data/{ticker}/candles?timeframe=1min`` endpoint
reads from that table, so the frontend sees real minute data once this runs.

WHY: the 30-min parquet under ``data/30min_data/`` covers 2000–present for
training, but the DB has no minute-level history. The $29 Massive "Starter" plan
provides minute aggregates (15-min delayed) — enough to backfill ~2 years and to
top up daily after market close.

API (Polygon-compatible aggregates — verified against massive.com/docs):
    GET {base}/v2/aggs/ticker/{TICKER}/range/{mult}/{span}/{from}/{to}
        ?adjusted=true&sort=asc&limit=50000
    Auth: ``Authorization: Bearer <key>`` header AND/OR ``?apiKey=<key>`` (both sent).
    Response: {"results": [{"t": <ms epoch>, "o","h","l","c","v","vw","n"}],
               "next_url": <cursor URL or absent>, "status": ...}
    Pagination: follow ``next_url`` until absent. Up to 50,000 bars/page.

TARGET: market_data_1min(time, ticker, open, high, low, close, volume, vwap,
    source='massive'). Idempotent upsert ON CONFLICT (ticker, time) — re-running
    is always safe; the same minute may be overwritten with fresher values.

RUN (from repo root; needs Postgres up + MASSIVE_API_KEY in .env. Use a Python
that has httpx+sqlalchemy+asyncpg — e.g. the backend venv):
    backend/.venv/Scripts/python -m data.ingestion.massive_loader backfill --dry-run --limit 50
    backend/.venv/Scripts/python -m data.ingestion.massive_loader backfill          # 2yr full universe
    backend/.venv/Scripts/python -m data.ingestion.massive_loader backfill --symbols AAPL MSFT NVDA
    backend/.venv/Scripts/python -m data.ingestion.massive_loader update --days 1    # after-close top-up
    make massive-backfill        make massive-update

RESUMABLE: each completed ticker is recorded under
``data/ingestion/.massive_state/<run-key>.done``; re-running skips finished
tickers (use --reset to re-fetch). Idempotent upserts make Ctrl-C safe at any
point — a half-loaded ticker is simply re-fetched on the next run.

SCALE: minute bars × 2 years × full universe (~12.6k tickers) is on the order of
billions of rows / hundreds of GB. Start with --limit/--symbols, or run the full
job paced. Mind your plan's request-rate limit (--rate / --concurrency; the
loader backs off on HTTP 429 honoring Retry-After).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("massive_loader")

_ET = ZoneInfo("America/New_York")
_DEFAULT_PARQUET_ROOT = Path(__file__).resolve().parents[1] / "30min_data"
_STATE_DIR = Path(__file__).resolve().parent / ".massive_state"
_UPSERT_CHUNK = 10_000
_PAGE_LIMIT = 50_000

# ── SQL ──────────────────────────────────────────────────────────────────────
# market_data_1min ships with only a (ticker, time) index; add a unique one so
# upserts have a conflict target. Same index the IBKR stream ensures — shared.
_INDEX_SQL = text(
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_1min_ticker_time "
    "ON market_data_1min (ticker, time)"
)
_UPSERT_SQL = text(
    """
    INSERT INTO market_data_1min (time, ticker, open, high, low, close, volume, vwap, source)
    VALUES (:time, :ticker, :open, :high, :low, :close, :volume, :vwap, 'massive')
    ON CONFLICT (ticker, time) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
        close = EXCLUDED.close, volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap, source = 'massive'
    """
)


# ── Config ───────────────────────────────────────────────────────────────────
class LoaderSettings(BaseSettings):
    """Env-backed defaults (reads the repo-root .env, like the rest of the app)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"


@dataclass(slots=True)
class LoaderConfig:
    mode: str  # 'backfill' | 'update'
    base_url: str
    api_key: str
    database_url: str
    tickers: list[str]
    limit: int | None
    date_from: str  # YYYY-MM-DD (ET)
    date_to: str  # YYYY-MM-DD (ET)
    multiplier: int
    timespan: str
    adjusted: bool
    concurrency: int
    rate: float  # max requests/sec (0 = unlimited)
    timeout: float
    use_checkpoint: bool
    reset: bool
    dry_run: bool


# ── Rate limiter ─────────────────────────────────────────────────────────────
class _RateLimiter:
    """Token-bucket-ish min-interval limiter shared across concurrent workers."""

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


# ── HTTP ─────────────────────────────────────────────────────────────────────
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


# ── Bars → rows ──────────────────────────────────────────────────────────────
def _results_to_rows(ticker: str, results: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for r in results:
        t = r.get("t")
        o, h, low, c = r.get("o"), r.get("h"), r.get("l"), r.get("c")
        if t is None or None in (o, h, low, c):
            continue
        vw = r.get("vw")
        rows.append(
            {
                "time": datetime.fromtimestamp(t / 1000.0, tz=UTC),
                "ticker": ticker,
                "open": float(o),
                "high": float(h),
                "low": float(low),
                "close": float(c),
                "volume": int(round(float(r.get("v") or 0))),
                "vwap": float(vw) if vw is not None else None,
            }
        )
    return rows


# ── DB ───────────────────────────────────────────────────────────────────────
async def _ensure_index(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(_INDEX_SQL)


async def _upsert(engine, rows: list[dict]) -> None:
    for i in range(0, len(rows), _UPSERT_CHUNK):
        async with engine.begin() as conn:
            await conn.execute(_UPSERT_SQL, rows[i : i + _UPSERT_CHUNK])


# ── Per-ticker load ──────────────────────────────────────────────────────────
async def _load_ticker(
    client: httpx.AsyncClient, engine, limiter: _RateLimiter, cfg: LoaderConfig, ticker: str
) -> int:
    adjusted = "true" if cfg.adjusted else "false"
    url: str | None = _with_key(
        f"{cfg.base_url}/v2/aggs/ticker/{ticker}/range/{cfg.multiplier}/{cfg.timespan}/"
        f"{cfg.date_from}/{cfg.date_to}?adjusted={adjusted}&sort=asc&limit={_PAGE_LIMIT}",
        cfg.api_key,
    )
    total = 0
    while url:
        data = await _get_json(client, url, limiter)
        if not data:
            break
        rows = _results_to_rows(ticker, data.get("results") or [])
        if rows:
            await _upsert(engine, rows)
            total += len(rows)
        nxt = data.get("next_url")
        url = _with_key(nxt, cfg.api_key) if nxt else None
    return total


# ── Universe resolution ──────────────────────────────────────────────────────
async def _resolve_tickers(cfg_tickers: list[str], source: str, parquet_root: Path,
                           tickers_file: str | None, engine) -> list[str]:
    if cfg_tickers:
        return sorted({t.strip().upper() for t in cfg_tickers if t.strip()})
    if tickers_file:
        lines = Path(tickers_file).read_text(encoding="utf-8").splitlines()
        return sorted({ln.strip().upper() for ln in lines if ln.strip()})
    if source == "db":
        async with engine.begin() as conn:
            res = await conn.execute(text("SELECT ticker FROM tickers WHERE is_active ORDER BY ticker"))
            return [row[0].upper() for row in res.fetchall()]
    # default: parquet filenames (the user's actual on-disk universe)
    return sorted({p.stem.upper() for p in parquet_root.rglob("*.parquet")})


# ── State / checkpoint ───────────────────────────────────────────────────────
def _state_path(cfg: LoaderConfig) -> Path:
    _STATE_DIR.mkdir(exist_ok=True)
    key = f"{cfg.mode}_{cfg.multiplier}{cfg.timespan}_{cfg.date_from}_{cfg.date_to}"
    return _STATE_DIR / f"{key}.done"


def _load_done(path: Path) -> set[str]:
    if path.exists():
        return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return set()


# ── Run ──────────────────────────────────────────────────────────────────────
async def run(cfg: LoaderConfig, *, source: str, parquet_root: Path, tickers_file: str | None) -> None:
    if not cfg.api_key:
        logger.error("MASSIVE_API_KEY is empty — set it in .env")
        return

    engine = create_async_engine(cfg.database_url, pool_size=cfg.concurrency + 2, max_overflow=4)
    try:
        await _ensure_index(engine)
        tickers = await _resolve_tickers(cfg.tickers, source, parquet_root, tickers_file, engine)
        if cfg.limit:
            tickers = tickers[: cfg.limit]

        state = _state_path(cfg)
        done: set[str] = set()
        if cfg.use_checkpoint and not cfg.reset:
            done = _load_done(state)
        todo = [t for t in tickers if t not in done]

        logger.info(
            "mode=%s | %s..%s | %dx%s bars | universe=%d done=%d todo=%d | conc=%d rate=%s",
            cfg.mode, cfg.date_from, cfg.date_to, cfg.multiplier, cfg.timespan,
            len(tickers), len(done), len(todo), cfg.concurrency, cfg.rate or "inf",
        )
        if cfg.dry_run:
            logger.info("dry-run — first 20 tickers: %s", ", ".join(todo[:20]))
            return
        if not todo:
            logger.info("nothing to do — all tickers already complete")
            return

        limiter = _RateLimiter(cfg.rate)
        sem = asyncio.Semaphore(cfg.concurrency)
        state_lock = asyncio.Lock()
        counters = {"done": 0, "bars": 0}

        async with httpx.AsyncClient(
            timeout=cfg.timeout, headers={"Authorization": f"Bearer {cfg.api_key}"}
        ) as client:

            async def worker(tk: str) -> None:
                async with sem:
                    try:
                        n = await _load_ticker(client, engine, limiter, cfg, tk)
                    except Exception as exc:  # noqa: BLE001 — skip + keep going, re-fetched next run
                        logger.error("FAILED %s: %r", tk, exc)
                        return
                counters["done"] += 1
                counters["bars"] += n
                if cfg.use_checkpoint:
                    async with state_lock:
                        with state.open("a", encoding="utf-8") as f:
                            f.write(tk + "\n")
                logger.info(
                    "[%d/%d] %s: %d bars (%d total)", counters["done"], len(todo), tk, n, counters["bars"]
                )

            await asyncio.gather(*(worker(t) for t in todo))

        logger.info("DONE — %d tickers, %d bars upserted into market_data_1min", counters["done"], counters["bars"])
    finally:
        await engine.dispose()


def _et_today() -> date:
    return datetime.now(_ET).date()


def _years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - years, day=28)


# Convenience entrypoint for the Celery after-close task (see ml/tasks).
async def run_update_default(days: int = 1, concurrency: int = 8, rate: float = 0.0) -> None:
    s = LoaderSettings()
    today = _et_today()
    cfg = LoaderConfig(
        mode="update",
        base_url=s.MASSIVE_BASE_URL,
        api_key=s.MASSIVE_API_KEY,
        database_url=s.DATABASE_URL,
        tickers=[],
        limit=None,
        date_from=(today - timedelta(days=days)).isoformat(),
        date_to=today.isoformat(),
        multiplier=1,
        timespan="minute",
        adjusted=True,
        concurrency=concurrency,
        rate=rate,
        timeout=60.0,
        use_checkpoint=False,
        reset=False,
        dry_run=False,
    )
    await run(cfg, source="parquet", parquet_root=_DEFAULT_PARQUET_ROOT, tickers_file=None)


# ── CLI ──────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Massive minute bars → market_data_1min.")
    p.add_argument("mode", choices=["backfill", "update"], help="backfill 2yr history, or daily top-up")
    p.add_argument("--symbols", nargs="*", default=None, help="Explicit tickers (overrides universe).")
    p.add_argument("--tickers-from", choices=["parquet", "db"], default="parquet",
                   help="Universe source when --symbols/--tickers-file omitted (default parquet).")
    p.add_argument("--tickers-file", default=None, help="Newline-delimited ticker file.")
    p.add_argument("--parquet-root", default=str(_DEFAULT_PARQUET_ROOT), help="Root scanned for *.parquet.")
    p.add_argument("--limit", type=int, default=None, help="Cap the universe to the first N tickers.")
    p.add_argument("--years", type=int, default=2, help="backfill: how many years back (default 2).")
    p.add_argument("--days", type=int, default=1, help="update: how many days back to refresh (default 1).")
    p.add_argument("--from", dest="date_from", default=None, help="Explicit start YYYY-MM-DD (ET).")
    p.add_argument("--to", dest="date_to", default=None, help="Explicit end YYYY-MM-DD (ET).")
    p.add_argument("--multiplier", type=int, default=1)
    p.add_argument("--timespan", default="minute",
                   choices=["minute", "hour", "day", "week", "month", "quarter", "year"])
    p.add_argument("--no-adjusted", action="store_true", help="Request raw (unadjusted) bars.")
    p.add_argument("--concurrency", type=int, default=8, help="Concurrent tickers in flight.")
    p.add_argument("--rate", type=float, default=0.0, help="Max requests/sec (0 = unlimited).")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--reset", action="store_true", help="Ignore the checkpoint and re-fetch everything.")
    p.add_argument("--dry-run", action="store_true", help="Print the plan and exit without calling the API.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = LoaderSettings()

    today = _et_today()
    if args.mode == "backfill":
        date_from = args.date_from or _years_ago(today, args.years).isoformat()
        date_to = args.date_to or today.isoformat()
        use_checkpoint = True
    else:  # update
        date_from = args.date_from or (today - timedelta(days=args.days)).isoformat()
        date_to = args.date_to or today.isoformat()
        use_checkpoint = False

    cfg = LoaderConfig(
        mode=args.mode,
        base_url=s.MASSIVE_BASE_URL,
        api_key=s.MASSIVE_API_KEY,
        database_url=s.DATABASE_URL,
        tickers=args.symbols or [],
        limit=args.limit,
        date_from=date_from,
        date_to=date_to,
        multiplier=args.multiplier,
        timespan=args.timespan,
        adjusted=not args.no_adjusted,
        concurrency=args.concurrency,
        rate=args.rate,
        timeout=args.timeout,
        use_checkpoint=use_checkpoint,
        reset=args.reset,
        dry_run=args.dry_run,
    )
    try:
        asyncio.run(
            run(cfg, source=args.tickers_from, parquet_root=Path(args.parquet_root),
                tickers_file=args.tickers_file)
        )
    except KeyboardInterrupt:
        logger.info("interrupted — re-run to resume (idempotent upserts; checkpoint preserved)")


if __name__ == "__main__":
    main()
