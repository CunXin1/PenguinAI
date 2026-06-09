"""
Earnings data scheduler — startup fetch + 2× daily (pre-market + post-market).

Pulls the Finnhub (free-tier) earnings calendar into the ``earnings`` table.
Before each fetch, ensures all IBKR core stocks exist in the ``tickers``
table (FK requirement: ``earnings.ticker → tickers.ticker``).

Schedule (ET, weekdays only):
  - Backend startup: immediate fetch
  - 08:00 ET: pre-market  (captures BMO actuals + refreshed calendar)
  - 18:00 ET: post-market  (captures AMC actuals after close)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import zoneinfo
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("app.earnings")

# ── Core stocks that must have earnings coverage ────────────────────────────
# Superset of IBKR stream symbols + bootstrap universe.  ON CONFLICT DO NOTHING
# means existing rows (with richer metadata from bootstrap) are never overwritten.
_CORE_STOCKS: dict[str, str] = {
    # Mega-cap tech
    "NVDA": "NVIDIA Corp.",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "AMZN": "Amazon.com Inc.",
    "GOOGL": "Alphabet Inc.",
    "GOOG": "Alphabet Inc. Class C",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "AVGO": "Broadcom Inc.",
    "ORCL": "Oracle Corp.",
    "NFLX": "Netflix Inc.",
    "CRM": "Salesforce Inc.",
    "QCOM": "Qualcomm Inc.",
    "AMD": "Advanced Micro Devices",
    "MU": "Micron Technology",
    "PLTR": "Palantir Technologies",
    "ADBE": "Adobe Inc.",
    # Semiconductor / hardware
    "INTC": "Intel Corp.",
    "MRVL": "Marvell Technology",
    "TSM": "Taiwan Semiconductor",
    "ARM": "ARM Holdings",
    "ASML": "ASML Holding NV",
    "WDC": "Western Digital",
    "STX": "Seagate Technology",
    # Software / cloud / AI
    "NOW": "ServiceNow Inc.",
    "APP": "AppLovin Corp.",
    "CRWV": "CoreWeave Inc.",
    "DELL": "Dell Technologies",
    "IBM": "International Business Machines",
    # Growth / speculative
    "HOOD": "Robinhood Markets",
    "RKLB": "Rocket Lab USA",
    "MSTR": "MicroStrategy Inc.",
    "NBIS": "Nebius Group",
    "LITE": "Lumentum Holdings",
    # Energy / industrial
    "BE": "Bloom Energy",
    "IREN": "Iris Energy",
    "GEV": "GE Vernova",
    # Healthcare
    "LLY": "Eli Lilly and Co.",
    "UNH": "UnitedHealth Group",
    "ABBV": "AbbVie Inc.",
    # Financials
    "JPM": "JPMorgan Chase",
    "BAC": "Bank of America",
    "GS": "Goldman Sachs",
    "V": "Visa Inc.",
    "MA": "Mastercard Inc.",
    # Energy
    "XOM": "Exxon Mobil Corp.",
    "CVX": "Chevron Corp.",
    # Consumer / retail
    "COST": "Costco Wholesale",
    "WMT": "Walmart Inc.",
    "HD": "Home Depot Inc.",
}

_FETCH_HOURS = (8, 18)  # 8 AM pre-market, 6 PM post-market ET
_ET = zoneinfo.ZoneInfo("America/New_York")


# ── Ensure core tickers exist ───────────────────────────────────────────────


async def ensure_core_tickers(db_url: str) -> int:
    """Insert missing core stocks into ``tickers`` (idempotent)."""
    engine = create_async_engine(db_url)
    added = 0
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT ticker FROM tickers"))
            existing = {row[0] for row in result}

            missing = {t: n for t, n in _CORE_STOCKS.items() if t not in existing}
            if not missing:
                return 0

            for ticker, name in missing.items():
                await conn.execute(
                    text(
                        "INSERT INTO tickers (ticker, name) "
                        "VALUES (:ticker, :name) "
                        "ON CONFLICT (ticker) DO NOTHING"
                    ),
                    {"ticker": ticker, "name": name},
                )
            added = len(missing)
            logger.info("added %d core tickers: %s", added, sorted(missing))
    except Exception:
        logger.warning("ensure_core_tickers failed (table may not exist yet)", exc_info=True)
    finally:
        await engine.dispose()
    return added


# ── Single fetch cycle ──────────────────────────────────────────────────────


async def fetch_earnings(db_url: str, days_back: int = 7, days_ahead: int = 30) -> int:
    """Ensure core tickers, then pull Finnhub earnings calendar."""
    await ensure_core_tickers(db_url)

    from data.earnings.finnhub import run_default

    return await run_default(days_back=days_back, days_ahead=days_ahead)


# ── Background scheduler ───────────────────────────────────────────────────


def run_scheduler(stop_event: threading.Event, db_url: str) -> None:
    """Fetch on startup, then 2× daily at 08:00 / 18:00 ET (weekdays)."""

    # ── Startup fetch ─────────────────────────────────────────────
    logger.info("initial fetch on startup")
    try:
        count = asyncio.run(fetch_earnings(db_url))
        logger.info("startup fetch complete (%d rows)", count)
    except Exception:
        logger.warning("startup fetch failed", exc_info=True)

    # ── Daily loop ────────────────────────────────────────────────
    while not stop_event.is_set():
        now_et = datetime.now(_ET)

        candidates = []
        for h in _FETCH_HOURS:
            t = now_et.replace(hour=h, minute=0, second=0, microsecond=0)
            if t <= now_et:
                t += timedelta(days=1)
            while t.weekday() >= 5:
                t += timedelta(days=1)
            candidates.append(t)

        target = min(candidates)
        wait_secs = (target - now_et).total_seconds()
        label = "pre-market" if target.hour == _FETCH_HOURS[0] else "post-market"
        logger.info(
            "next fetch: %s ET (%s, %.1fh)",
            target.strftime("%Y-%m-%d %H:%M"),
            label,
            wait_secs / 3600,
        )

        if stop_event.wait(timeout=wait_secs):
            break

        logger.info("%s fetch starting", label)
        try:
            count = asyncio.run(fetch_earnings(db_url))
            logger.info("%s fetch complete (%d rows)", label, count)
        except Exception:
            logger.warning("%s fetch failed", label, exc_info=True)
