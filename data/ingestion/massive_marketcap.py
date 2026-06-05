"""Fetch market cap for the universe from Massive and store it.

Sizes the market-map / heatmap tiles and gives the screener a real sort key.
Massive's per-ticker details endpoint (``/v3/reference/tickers/{sym}``) returns
``market_cap`` + shares outstanding (the bulk listing does not), so this makes
one call per symbol, concurrently and rate-limited.

Writes BOTH:
  1. DB   — ``tickers.market_cap`` (BIGINT).
  2. File — ``data/reference/market_cap.parquet`` (symbol, market_cap, shares).

RUN (repo root; needs MASSIVE_API_KEY in .env):
    backend/.venv/Scripts/python -m data.ingestion.massive_marketcap
    backend/.venv/Scripts/python -m data.ingestion.massive_marketcap --dry-run   # parquet only
"""

import argparse
import asyncio
import logging
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.ingestion.massive_reference import _get_json, _RateLimiter, _with_key, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("massive_marketcap")

_OUT = Path(__file__).resolve().parents[1] / "reference" / "market_cap.parquet"
_RATE_PER_SEC = 40.0
_CONCURRENCY = 12


async def _fetch_one(
    client: httpx.AsyncClient,
    base: str,
    key: str,
    limiter: _RateLimiter,
    sem: asyncio.Semaphore,
    symbol: str,
) -> tuple[str, float | None, float | None]:
    async with sem:
        url = _with_key(f"{base}/v3/reference/tickers/{symbol}", key)
        try:
            j = await _get_json(client, url, limiter)
        except httpx.HTTPStatusError:
            return symbol, None, None  # 404 etc. → no market cap
        r = (j or {}).get("results") or {}
        shares = r.get("share_class_shares_outstanding") or r.get("weighted_shares_outstanding")
        return symbol, r.get("market_cap"), shares


async def run(dry_run: bool = False) -> None:
    if not settings.MASSIVE_API_KEY:
        logger.error("MASSIVE_API_KEY is empty — set it in .env")
        return

    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        symbols = [
            r[0] for r in (await db.execute(text("SELECT symbol FROM instruments ORDER BY symbol"))).all()
        ]
    logger.info("universe: %d symbols", len(symbols))

    limiter = _RateLimiter(_RATE_PER_SEC)
    sem = asyncio.Semaphore(_CONCURRENCY)
    done = 0
    results: list[tuple[str, float | None, float | None]] = []

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        tasks = [
            asyncio.ensure_future(_fetch_one(client, base, key, limiter, sem, s)) for s in symbols
        ]
        for fut in asyncio.as_completed(tasks):
            results.append(await fut)
            done += 1
            if done % 500 == 0:
                logger.info("  %d / %d fetched", done, len(symbols))

    records = [{"symbol": s, "market_cap": mc, "shares": sh} for s, mc, sh in results]
    df = pd.DataFrame(records).sort_values("symbol").reset_index(drop=True)
    have = int(df["market_cap"].notna().sum())
    logger.info("market_cap resolved: %d / %d (%.1f%%)", have, len(df), 100.0 * have / len(df))

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_OUT, index=False)
    logger.info("wrote parquet → %s (%d rows)", _OUT, len(df))

    if dry_run:
        logger.info("--dry-run: skipped DB write")
        await engine.dispose()
        return

    # market_cap is BIGINT — round floats to int; skip rows without a value.
    params = [
        {"symbol": r["symbol"], "mcap": int(r["market_cap"])}
        for r in records
        if r["market_cap"]
    ]
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE tickers SET market_cap = :mcap WHERE ticker = :symbol"), params
        )
        await db.commit()
    logger.info("updated %d tickers.market_cap rows in DB", len(params))
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch universe market cap from Massive.")
    ap.add_argument("--dry-run", action="store_true", help="write parquet only; no DB update")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
