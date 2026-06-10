"""
Earnings data scheduler — startup fetch + 2× daily (pre-market + post-market).

Pulls the Finnhub (free-tier) earnings calendar into the ``earnings`` table.
Before each fetch, ensures all IBKR core stocks exist in the ``tickers``
table (FK requirement: ``earnings.ticker → tickers.ticker``).

Schedule (ET, weekdays only):
  - Backend startup: immediate fetch
  - 08:00 ET: pre-market  (captures BMO actuals + refreshed calendar)
  - 18:00 ET: post-market  (captures AMC actuals after close)
  - Report-time fast-poll: during the BMO (06:00–11:00) and AMC (16:00–21:00)
    windows, whenever a company is due to report *today* but its ``eps_actual``
    is still NULL, re-fetch every 15 min until the actuals land (or the window
    closes). This pulls just-published results in quickly instead of waiting
    for the next twice-daily fetch.
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

# Report-time fast-poll: how often to re-fetch while actuals are still pending.
_POLL_INTERVAL = timedelta(minutes=15)
# ET windows where freshly-published actuals are expected to land, with the
# Finnhub ``report_hour`` codes that belong to each. "" matches rows whose hour
# is unknown (NULL) — poll those in both windows since we can't tell when.
_REPORT_WINDOWS: tuple[tuple[int, int, tuple[str, ...]], ...] = (
    (6, 11, ("bmo", "")),  # pre-market reports
    (16, 21, ("amc", "dmh", "")),  # after-close reports
)


def _active_report_window(now_et: datetime) -> tuple[str, ...] | None:
    """Sessions expected to be publishing now, or None outside any window/weekend."""
    if now_et.weekday() >= 5:
        return None
    for start, end, sessions in _REPORT_WINDOWS:
        if start <= now_et.hour < end:
            return sessions
    return None


async def count_pending_reports(db_url: str, sessions: tuple[str, ...]) -> int:
    """Count today's (ET) earnings rows for ``sessions`` still missing ``eps_actual``."""
    engine = create_async_engine(db_url)
    try:
        today = datetime.now(_ET).date()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM earnings "
                    "WHERE report_date = :today AND eps_actual IS NULL "
                    "AND COALESCE(LOWER(report_hour), '') = ANY(:sessions)"
                ),
                {"today": today, "sessions": list(sessions)},
            )
            return int(result.scalar() or 0)
    except Exception:
        logger.warning("count_pending_reports failed", exc_info=True)
        return 0
    finally:
        await engine.dispose()


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

        # ── Report-time fast-poll ─────────────────────────────────
        # If we're inside a publish window and some of today's reports haven't
        # posted actuals yet, re-fetch every _POLL_INTERVAL until they land.
        sessions = _active_report_window(now_et)
        if sessions is not None:
            pending = asyncio.run(count_pending_reports(db_url, sessions))
            if pending > 0:
                logger.info("report window active — %d pending today, fast fetch", pending)
                try:
                    count = asyncio.run(fetch_earnings(db_url))
                    logger.info("fast fetch complete (%d rows)", count)
                except Exception:
                    logger.warning("fast fetch failed", exc_info=True)
                if stop_event.wait(timeout=_POLL_INTERVAL.total_seconds()):
                    break
                continue

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
