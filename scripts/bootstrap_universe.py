"""
Bootstrap the ticker universe into the tickers table.
Run once after DB schema creation.
Usage: python scripts/bootstrap_universe.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Core universe ─────────────────────────────────────────────────────────────
TICKER_UNIVERSE = [
    # Mega-cap tech
    {"ticker": "AAPL",  "name": "Apple Inc.",              "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "mega_cap"]},
    {"ticker": "MSFT",  "name": "Microsoft Corp.",         "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "mega_cap"]},
    {"ticker": "NVDA",  "name": "NVIDIA Corp.",            "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "ai", "mega_cap"]},
    {"ticker": "AMZN",  "name": "Amazon.com Inc.",         "sector": "Consumer",       "exchange": "NASDAQ", "tags": ["tech", "sp500", "mega_cap"]},
    {"ticker": "GOOGL", "name": "Alphabet Inc. Class A",   "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "mega_cap"]},
    {"ticker": "META",  "name": "Meta Platforms Inc.",     "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "mega_cap"]},
    {"ticker": "TSLA",  "name": "Tesla Inc.",              "sector": "Automotive",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "ev"]},
    {"ticker": "AVGO",  "name": "Broadcom Inc.",           "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "semiconductor"]},
    {"ticker": "PLTR",  "name": "Palantir Technologies",   "sector": "Technology",     "exchange": "NYSE",   "tags": ["tech", "ai", "sp500"]},
    {"ticker": "AMD",   "name": "Advanced Micro Devices",  "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "semiconductor"]},
    {"ticker": "ORCL",  "name": "Oracle Corp.",            "sector": "Technology",     "exchange": "NYSE",   "tags": ["tech", "sp500"]},
    {"ticker": "NFLX",  "name": "Netflix Inc.",            "sector": "Media",          "exchange": "NASDAQ", "tags": ["tech", "sp500", "streaming"]},
    {"ticker": "CRM",   "name": "Salesforce Inc.",         "sector": "Technology",     "exchange": "NYSE",   "tags": ["tech", "sp500"]},
    {"ticker": "ADBE",  "name": "Adobe Inc.",              "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500"]},
    {"ticker": "QCOM",  "name": "Qualcomm Inc.",           "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "semiconductor"]},
    {"ticker": "MU",    "name": "Micron Technology",       "sector": "Technology",     "exchange": "NASDAQ", "tags": ["tech", "sp500", "semiconductor"]},
    # Major ETFs
    {"ticker": "SPY",   "name": "SPDR S&P 500 ETF",       "sector": "ETF",            "exchange": "NYSE",   "tags": ["etf", "index"]},
    {"ticker": "QQQ",   "name": "Invesco QQQ ETF",         "sector": "ETF",            "exchange": "NASDAQ", "tags": ["etf", "index", "tech"]},
    {"ticker": "IWM",   "name": "iShares Russell 2000",    "sector": "ETF",            "exchange": "NYSE",   "tags": ["etf", "index", "small_cap"]},
    {"ticker": "DIA",   "name": "SPDR Dow Jones ETF",      "sector": "ETF",            "exchange": "NYSE",   "tags": ["etf", "index"]},
    {"ticker": "XLK",   "name": "Technology Select SPDR",  "sector": "ETF",            "exchange": "NYSE",   "tags": ["etf", "tech"]},
    {"ticker": "GLD",   "name": "SPDR Gold Shares",        "sector": "ETF",            "exchange": "NYSE",   "tags": ["etf", "commodity", "gold"]},
    {"ticker": "TLT",   "name": "iShares 20+ Year Treasury","sector": "ETF",           "exchange": "NASDAQ", "tags": ["etf", "bonds"]},
    # Financials
    {"ticker": "JPM",   "name": "JPMorgan Chase",          "sector": "Financials",     "exchange": "NYSE",   "tags": ["finance", "sp500"]},
    {"ticker": "BAC",   "name": "Bank of America",         "sector": "Financials",     "exchange": "NYSE",   "tags": ["finance", "sp500"]},
    {"ticker": "GS",    "name": "Goldman Sachs",           "sector": "Financials",     "exchange": "NYSE",   "tags": ["finance", "sp500"]},
    {"ticker": "V",     "name": "Visa Inc.",               "sector": "Financials",     "exchange": "NYSE",   "tags": ["finance", "sp500"]},
    {"ticker": "MA",    "name": "Mastercard Inc.",         "sector": "Financials",     "exchange": "NYSE",   "tags": ["finance", "sp500"]},
    # Healthcare
    {"ticker": "LLY",   "name": "Eli Lilly and Co.",       "sector": "Healthcare",     "exchange": "NYSE",   "tags": ["healthcare", "sp500"]},
    {"ticker": "UNH",   "name": "UnitedHealth Group",      "sector": "Healthcare",     "exchange": "NYSE",   "tags": ["healthcare", "sp500"]},
    {"ticker": "ABBV",  "name": "AbbVie Inc.",             "sector": "Healthcare",     "exchange": "NYSE",   "tags": ["healthcare", "sp500"]},
    # Energy
    {"ticker": "XOM",   "name": "Exxon Mobil Corp.",       "sector": "Energy",         "exchange": "NYSE",   "tags": ["energy", "sp500"]},
    {"ticker": "CVX",   "name": "Chevron Corp.",           "sector": "Energy",         "exchange": "NYSE",   "tags": ["energy", "sp500"]},
    # Retail / Consumer
    {"ticker": "COST",  "name": "Costco Wholesale",        "sector": "Consumer",       "exchange": "NASDAQ", "tags": ["retail", "sp500"]},
    {"ticker": "WMT",   "name": "Walmart Inc.",            "sector": "Consumer",       "exchange": "NYSE",   "tags": ["retail", "sp500"]},
    {"ticker": "HD",    "name": "Home Depot Inc.",         "sector": "Consumer",       "exchange": "NYSE",   "tags": ["retail", "sp500"]},
]


async def bootstrap():
    from backend.app.core.config import settings
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        for t in TICKER_UNIVERSE:
            await db.execute(
                text("""
                    INSERT INTO tickers (ticker, name, sector, exchange, tags)
                    VALUES (:ticker, :name, :sector, :exchange, :tags)
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        sector = EXCLUDED.sector,
                        tags = EXCLUDED.tags
                """),
                {**t, "tags": t["tags"]},
            )
        await db.commit()

    logger.info("Bootstrapped %d tickers into universe", len(TICKER_UNIVERSE))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(bootstrap())
