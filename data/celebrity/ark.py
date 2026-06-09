"""ARK Invest daily trades → ``celebrity_holdings`` table ingestion.

Free, no API key. Fetches recent ARK trade data from the arkfunds.io
public API for all major ARK ETFs (ARKK, ARKW, ARKG, ARKF, ARKQ).

RUN (from repo root, with .env present and Postgres up):
    python -m data.celebrity.ark
    make fetch-ark
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("celebrity_ark")

ARK_FUNDS = ["ARKK", "ARKW", "ARKG", "ARKF", "ARKQ"]
ARK_API_BASE = "https://arkfunds.io/api/v2/etf/trades"

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


def _parse_trade(item: dict, universe: set[str]) -> dict | None:
    ticker = (item.get("ticker") or "").strip().upper()
    if not ticker or ticker not in universe:
        return None

    direction = (item.get("direction") or "").strip()
    if direction.lower() == "buy":
        action = "BUY"
    elif direction.lower() == "sell":
        action = "SELL"
    else:
        return None

    raw_date = item.get("date")
    if not raw_date:
        return None
    try:
        reported_at = datetime.strptime(str(raw_date), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None

    shares = item.get("shares")
    if isinstance(shares, str):
        try:
            shares = int(shares.replace(",", ""))
        except ValueError:
            shares = None
    elif isinstance(shares, (int, float)):
        shares = int(shares)
    else:
        shares = None

    fund = item.get("fund") or item.get("etf") or ""

    return {
        "reported_at": reported_at,
        "celebrity": "cathie_wood",
        "ticker": ticker,
        "action": action,
        "shares": shares,
        "value_usd": None,
        "source_type": "daily_disclosure",
        "filing_url": f"https://ark-funds.com/active-etfs/{fund.lower()}/" if fund else None,
    }


async def _fetch_fund_trades(
    client: httpx.AsyncClient,
    fund: str,
    date_from: str,
    date_to: str,
) -> list[dict]:
    try:
        resp = await client.get(
            ARK_API_BASE,
            params={"symbol": fund, "date_from": date_from, "date_to": date_to},
        )
        if resp.status_code != 200:
            logger.warning("  %s: HTTP %d", fund, resp.status_code)
            return []
        data = resp.json()
        trades = data.get("trades") or data if isinstance(data, list) else data.get("trades", [])
        if isinstance(trades, list):
            for t in trades:
                t["fund"] = fund
            return trades
        return []
    except Exception as exc:
        logger.warning("  %s: fetch failed: %s", fund, exc)
        return []


async def run_loader(database_url: str, days_back: int = 30) -> int:
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

        now = datetime.now(UTC)
        date_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        date_to = now.strftime("%Y-%m-%d")

        all_trades: list[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for fund in ARK_FUNDS:
                logger.info("fetching %s trades (%s → %s)...", fund, date_from, date_to)
                trades = await _fetch_fund_trades(client, fund, date_from, date_to)
                all_trades.extend(trades)
                await asyncio.sleep(0.5)

        logger.info("total raw trades fetched: %d", len(all_trades))

        rows: list[dict] = []
        for item in all_trades:
            parsed = _parse_trade(item, universe)
            if parsed:
                rows.append(parsed)

        if not rows:
            logger.info("no rows matched universe — nothing to upsert")
            return 0

        deduped: dict[tuple, dict] = {}
        for r in rows:
            key = (r["celebrity"], r["ticker"], r["reported_at"], r["action"])
            if key in deduped:
                existing = deduped[key]
                if r["shares"] and existing["shares"]:
                    existing["shares"] += r["shares"]
                elif r["shares"]:
                    existing["shares"] = r["shares"]
            else:
                deduped[key] = r
        rows = list(deduped.values())

        written = 0
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            async with engine.begin() as conn:
                await conn.execute(_UPSERT_SQL, batch)
            written += len(batch)

        logger.info("upserted %d ARK trades", written)
        return written
    finally:
        await engine.dispose()


async def run_default(days_back: int = 30) -> int:
    s = LoaderSettings()
    return await run_loader(s.DATABASE_URL, days_back=days_back)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load ARK Invest trades into celebrity_holdings.")
    parser.add_argument("--days-back", type=int, default=30, help="Lookback window in days.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    s = LoaderSettings()
    db_url = args.database_url or s.DATABASE_URL
    logger.info("ARK trades → celebrity_holdings (last %d days)", args.days_back)
    try:
        asyncio.run(run_loader(db_url, days_back=args.days_back))
    except KeyboardInterrupt:
        logger.info("interrupted")


if __name__ == "__main__":
    main()
