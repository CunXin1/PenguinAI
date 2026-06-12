"""Fetch company / ETF names for the full universe from Massive and store them.

Massive's reference API is Polygon-compatible. We resolve a name (+ primary
exchange and security type) for every symbol in the ``instruments`` table (the
~6300 symbols that have 30-min data) and persist to BOTH:

  1. DB   — backfill ``tickers.name`` / ``tickers.exchange`` (the app universe).
  2. File — ``data/reference/tickers_reference.parquet`` (one row per symbol).

Active symbols are resolved in bulk via the paged listing (~1000/page, ~12 calls
for the whole active market). Symbols not in the active listing (delisted — the
data goes back to 2000) are looked up individually with ``active=false``.

RUN (repo root; needs MASSIVE_API_KEY in .env; backend venv has httpx + pandas +
sqlalchemy + asyncpg):

    backend/.venv/Scripts/python -m data.ingestion.massive_reference
    backend/.venv/Scripts/python -m data.ingestion.massive_reference --dry-run   # parquet only, no DB write
"""

import argparse
import asyncio
import logging
from pathlib import Path

import httpx
import pandas as pd
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("massive_reference")

_OUT = Path(__file__).resolve().parents[1] / "reference" / "tickers_reference.parquet"

_RATE_PER_SEC = 25.0  # polite cap for the individual delisted lookups
_CONCURRENCY = 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"


settings = Settings()


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


def _with_key(url: str, key: str) -> str:
    if not key or "apiKey=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}apiKey={key}"


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


def _rec(x: dict) -> dict:
    return {
        "name": x.get("name"),
        "exchange": x.get("primary_exchange"),
        "type": x.get("type"),
        "active": bool(x.get("active")),
    }


async def _fetch_active_listing(
    client: httpx.AsyncClient, base: str, key: str, limiter: _RateLimiter
) -> dict[str, dict]:
    """Page the full active stocks+ETFs listing → {ticker: record}."""
    ref: dict[str, dict] = {}
    url = _with_key(f"{base}/v3/reference/tickers?market=stocks&active=true&limit=1000", key)
    pages = 0
    while url:
        j = await _get_json(client, url, limiter)
        if not j:
            break
        pages += 1
        for x in j.get("results") or []:
            t = x.get("ticker")
            if t and t not in ref:
                ref[t] = _rec(x)
        nxt = j.get("next_url")
        url = _with_key(nxt, key) if nxt else None
        if pages % 5 == 0:
            logger.info("  active listing: %d pages, %d tickers", pages, len(ref))
    logger.info("active listing complete: %d pages, %d tickers", pages, len(ref))
    return ref


async def _lookup_one(
    client: httpx.AsyncClient,
    base: str,
    key: str,
    limiter: _RateLimiter,
    sem: asyncio.Semaphore,
    symbol: str,
) -> tuple[str, dict | None]:
    """Resolve a single symbol (delisted first, then active as a backstop)."""
    async with sem:
        for active in ("false", "true"):
            url = _with_key(
                f"{base}/v3/reference/tickers?ticker={symbol}&active={active}&limit=1", key
            )
            j = await _get_json(client, url, limiter)
            res = (j or {}).get("results") or []
            if res:
                return symbol, _rec(res[0])
    return symbol, None


async def run(dry_run: bool = False) -> None:
    if not settings.MASSIVE_API_KEY:
        logger.error("MASSIVE_API_KEY is empty — set it in .env")
        return

    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        rows = (
            await db.execute(text("SELECT symbol, asset_type FROM instruments ORDER BY symbol"))
        ).all()
    symbols = [r[0] for r in rows]
    asset_type = {r[0]: r[1] for r in rows}
    logger.info("universe: %d symbols", len(symbols))

    limiter = _RateLimiter(_RATE_PER_SEC)
    sem = asyncio.Semaphore(_CONCURRENCY)
    resolved: dict[str, dict] = {}

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        listing = await _fetch_active_listing(client, base, key, limiter)
        targets = set(symbols)
        for t in targets & listing.keys():
            resolved[t] = listing[t]

        unmatched = [s for s in symbols if s not in resolved]
        logger.info(
            "matched from active listing: %d; delisted/individual lookups: %d",
            len(resolved),
            len(unmatched),
        )
        results = await asyncio.gather(
            *[_lookup_one(client, base, key, limiter, sem, s) for s in unmatched]
        )
    for sym, rec in results:
        if rec:
            resolved[sym] = rec

    records = [
        {
            "symbol": s,
            "name": resolved.get(s, {}).get("name"),
            "exchange": resolved.get(s, {}).get("exchange"),
            "type": resolved.get(s, {}).get("type"),
            "active": resolved.get(s, {}).get("active"),
            "asset_type": asset_type[s],
            "source": "massive",
        }
        for s in symbols
    ]
    df = pd.DataFrame(records)
    named = int(df["name"].notna().sum())
    logger.info("resolved names: %d / %d (%.1f%%)", named, len(df), 100.0 * named / len(df))

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_OUT, index=False)
    logger.info("wrote parquet → %s (%d rows)", _OUT, len(df))

    if dry_run:
        logger.info("--dry-run: skipped DB write")
        await engine.dispose()
        return

    # Upsert (not just UPDATE): every instruments symbol gets a tickers row, so
    # `tickers` is the authoritative symbol → company-name dimension for the whole
    # universe. On conflict we only refresh name/exchange — is_active is owned by
    # symbol_validation and must not be clobbered here; new rows default to the
    # listing's active flag.
    params = [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "exchange": r["exchange"],
            "is_active": bool(r["active"]) if r["active"] is not None else True,
        }
        for r in records
        if r["name"]
    ]
    async with SessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO tickers (ticker, name, exchange, is_active) "
                "VALUES (:symbol, :name, :exchange, :is_active) "
                "ON CONFLICT (ticker) DO UPDATE SET "
                "name = EXCLUDED.name, "
                "exchange = COALESCE(EXCLUDED.exchange, tickers.exchange)"
            ),
            params,
        )
        await db.commit()
    logger.info("upserted %d tickers rows in DB", len(params))
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch universe company names from Massive.")
    ap.add_argument("--dry-run", action="store_true", help="write parquet only; no DB update")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
