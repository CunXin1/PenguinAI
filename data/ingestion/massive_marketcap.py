"""Fetch market cap + SIC sector/industry for the universe from Massive and store it.

Sizes the market-map / heatmap tiles and gives the screener a real sort key.
Massive's per-ticker details endpoint (``/v3/reference/tickers/{sym}``) returns
``market_cap`` + shares outstanding + ``sic_code``/``sic_description`` (the bulk
listing does not), so this makes one call per symbol, concurrently and
rate-limited. The same response also classifies the company, so we capture the
SIC fields here for free → ``tickers.sector`` (coarse bucket) + ``industry``
(verbatim SIC description), which were previously empty for all but ~36 tickers.

Writes BOTH:
  1. DB   — ``tickers.market_cap`` (BIGINT), ``tickers.sector``, ``tickers.industry``.
  2. File — ``data/reference/market_cap.parquet`` (symbol, market_cap, shares,
            sic_code, sic_description, sector).

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
from data.ingestion.sic_sectors import sic_to_sector

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
) -> dict:
    async with sem:
        url = _with_key(f"{base}/v3/reference/tickers/{symbol}", key)
        try:
            j = await _get_json(client, url, limiter)
        except httpx.HTTPStatusError:
            return {"symbol": symbol}  # 404 etc. → no details
        r = (j or {}).get("results") or {}
        shares = r.get("share_class_shares_outstanding") or r.get("weighted_shares_outstanding")
        return {
            "symbol": symbol,
            "market_cap": r.get("market_cap"),
            "shares": shares,
            "sic_code": r.get("sic_code"),
            "sic_description": r.get("sic_description"),
        }


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
    results: list[dict] = []

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

    records = [
        {
            "symbol": r["symbol"],
            "market_cap": r.get("market_cap"),
            "shares": r.get("shares"),
            "sic_code": r.get("sic_code"),
            "sic_description": r.get("sic_description"),
            "sector": sic_to_sector(r.get("sic_code")),
        }
        for r in results
    ]
    df = pd.DataFrame(records).sort_values("symbol").reset_index(drop=True)
    have = int(df["market_cap"].notna().sum())
    sectored = int(df["sector"].notna().sum())
    logger.info("market_cap resolved: %d / %d (%.1f%%)", have, len(df), 100.0 * have / len(df))
    logger.info("sector classified: %d / %d (%.1f%%)", sectored, len(df), 100.0 * sectored / len(df))

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_OUT, index=False)
    logger.info("wrote parquet → %s (%d rows)", _OUT, len(df))

    if dry_run:
        logger.info("--dry-run: skipped DB write")
        await engine.dispose()
        return

    # market_cap is BIGINT — round floats to int; skip rows without a value.
    mcap_params = [
        {"symbol": r["symbol"], "mcap": int(r["market_cap"])}
        for r in records
        if r["market_cap"]
    ]
    # sector/industry: COALESCE so we never overwrite an existing value with NULL
    # (ETFs and unmapped SIC codes resolve to None and are left untouched).
    class_params = [
        {
            "symbol": r["symbol"],
            "sector": r["sector"],
            "industry": r["sic_description"],
        }
        for r in records
        if r["sector"] or r["sic_description"]
    ]
    async with SessionLocal() as db:
        if mcap_params:
            await db.execute(
                text("UPDATE tickers SET market_cap = :mcap WHERE ticker = :symbol"), mcap_params
            )
        if class_params:
            await db.execute(
                text(
                    "UPDATE tickers SET "
                    "sector = COALESCE(:sector, sector), "
                    "industry = COALESCE(:industry, industry) "
                    "WHERE ticker = :symbol"
                ),
                class_params,
            )
        await db.commit()
    logger.info(
        "updated DB: %d market_cap rows, %d sector/industry rows",
        len(mcap_params),
        len(class_params),
    )
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Fetch universe market cap + SIC sector/industry from Massive."
    )
    ap.add_argument("--dry-run", action="store_true", help="write parquet only; no DB update")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
