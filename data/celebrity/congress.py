"""House + Senate Stock Watcher → ``celebrity_holdings`` table ingestion.

Free, no API key. Downloads the full transaction JSON from the public S3
buckets maintained by the House/Senate Stock Watcher projects and upserts
transactions from a curated list of politicians into celebrity_holdings.

RUN (from repo root, with .env present and Postgres up):
    python -m data.celebrity.congress
    make fetch-congress
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from datetime import UTC, datetime

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("celebrity_congress")

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

CONGRESS_CELEBRITIES: dict[str, str] = {
    "Hon. Nancy Pelosi": "pelosi",
    "Nancy Pelosi": "pelosi",
    "Tommy Tuberville": "tuberville",
    "Daniel S. Goldman": "goldman",
    "Mark Green": "mark_green",
    "Josh Gottheimer": "gottheimer",
    "Ro Khanna": "khanna",
    "Michael McCaul": "mccaul",
    "Dan Crenshaw": "crenshaw",
    "Marjorie Taylor Greene": "mtg",
}

_ACTION_MAP: dict[str, str] = {
    "purchase": "BUY",
    "sale_full": "SELL",
    "sale_partial": "SELL",
    "sale": "SELL",
    "exchange": "BUY",
}

_UNIVERSE_SQL = text("SELECT ticker FROM tickers")
_UPSERT_SQL = text("""
    INSERT INTO celebrity_holdings
        (reported_at, celebrity, ticker, action, shares, value_usd, source_type, filing_url)
    VALUES
        (:reported_at, :celebrity, :ticker, :action, :shares, :value_usd, :source_type, :filing_url)
    ON CONFLICT (celebrity, ticker, reported_at, action) DO UPDATE SET
        shares    = EXCLUDED.shares,
        value_usd = EXCLUDED.value_usd,
        filing_url = EXCLUDED.filing_url
""")


class LoaderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"


def _parse_amount(amount_str: str | None) -> int | None:
    """Parse range string like '$1,001 - $15,000' → midpoint integer."""
    if not amount_str:
        return None
    nums = re.findall(r"\d+", amount_str.replace(",", ""))
    if not nums:
        return None
    values = [int(n) for n in nums]
    if len(values) >= 2:
        return (values[0] + values[1]) // 2
    return values[0]


def _parse_date(raw: str | None) -> datetime | None:
    """Parse date strings in various formats."""
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_house_row(item: dict, universe: set[str]) -> dict | None:
    rep = item.get("representative", "")
    celeb_slug = CONGRESS_CELEBRITIES.get(rep)
    if not celeb_slug:
        return None

    ticker = (item.get("ticker") or "").strip().upper().replace("--", "")
    if not ticker or ticker not in universe:
        return None

    action = _ACTION_MAP.get((item.get("type") or "").lower())
    if not action:
        return None

    reported_at = _parse_date(item.get("transaction_date"))
    if not reported_at:
        return None

    return {
        "reported_at": reported_at,
        "celebrity": celeb_slug,
        "ticker": ticker,
        "action": action,
        "shares": None,
        "value_usd": _parse_amount(item.get("amount")),
        "source_type": "daily_disclosure",
        "filing_url": item.get("disclosure_url"),
    }


def _parse_senate_row(item: dict, universe: set[str]) -> dict | None:
    senator = item.get("senator", "") or item.get("first_name", "")
    if isinstance(item.get("last_name"), str):
        senator = f"{item.get('first_name', '')} {item['last_name']}".strip()

    celeb_slug = CONGRESS_CELEBRITIES.get(senator)
    if not celeb_slug:
        return None

    ticker = (item.get("ticker") or "").strip().upper().replace("--", "")
    if not ticker or ticker not in universe:
        return None

    tx_type = (item.get("type") or "").lower()
    if "purchase" in tx_type:
        action = "BUY"
    elif "sale" in tx_type:
        action = "SELL"
    elif "exchange" in tx_type:
        action = "BUY"
    else:
        return None

    reported_at = _parse_date(item.get("transaction_date"))
    if not reported_at:
        return None

    return {
        "reported_at": reported_at,
        "celebrity": celeb_slug,
        "ticker": ticker,
        "action": action,
        "shares": None,
        "value_usd": _parse_amount(item.get("amount")),
        "source_type": "daily_disclosure",
        "filing_url": item.get("disclosure_url"),
    }


async def run_loader(database_url: str) -> int:
    engine = create_async_engine(database_url)
    try:
        universe = set()
        async with engine.connect() as conn:
            result = await conn.execute(_UNIVERSE_SQL)
            universe = {row[0] for row in result}

        if not universe:
            logger.warning("tickers table is empty — run bootstrap_universe.py first")
            return 0
        logger.info("universe: %d known tickers", len(universe))

        rows: list[dict] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.info("fetching House transactions...")
            try:
                resp = await client.get(HOUSE_URL)
                resp.raise_for_status()
                house_data = resp.json()
                for item in house_data:
                    parsed = _parse_house_row(item, universe)
                    if parsed:
                        rows.append(parsed)
                logger.info("  House: %d matched rows from %d total", len(rows), len(house_data))
            except Exception as exc:
                logger.warning("House fetch failed: %s", exc)

            house_count = len(rows)
            logger.info("fetching Senate transactions...")
            try:
                resp = await client.get(SENATE_URL)
                resp.raise_for_status()
                senate_data = resp.json()
                for item in senate_data:
                    parsed = _parse_senate_row(item, universe)
                    if parsed:
                        rows.append(parsed)
                logger.info(
                    "  Senate: %d matched rows from %d total",
                    len(rows) - house_count,
                    len(senate_data),
                )
            except Exception as exc:
                logger.warning("Senate fetch failed: %s", exc)

        if not rows:
            logger.info("no rows matched — nothing to upsert")
            return 0

        deduped: dict[tuple, dict] = {}
        for r in rows:
            key = (r["celebrity"], r["ticker"], r["reported_at"], r["action"])
            deduped[key] = r
        rows = list(deduped.values())

        written = 0
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            async with engine.begin() as conn:
                await conn.execute(_UPSERT_SQL, batch)
            written += len(batch)

        logger.info("upserted %d congressional trades", written)
        return written
    finally:
        await engine.dispose()


async def run_default() -> int:
    s = LoaderSettings()
    return await run_loader(s.DATABASE_URL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load congressional trades into celebrity_holdings.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    s = LoaderSettings()
    db_url = args.database_url or s.DATABASE_URL
    logger.info("Congressional trades → celebrity_holdings")
    try:
        asyncio.run(run_loader(db_url))
    except KeyboardInterrupt:
        logger.info("interrupted")


if __name__ == "__main__":
    main()
