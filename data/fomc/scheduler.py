"""FOMC data scheduler — runs as a backend lifespan thread.

Manages four data sources:
  1. Fed funds rate: FRED API (or hardcoded seed) — startup, post-FOMC (1h/1d/3d), weekly Friday
  2. FOMC statements: scrape + FinBERT score — startup, then daily at 15:00 ET
  3. FOMC news: Google News RSS — startup, then every 30 min
  4. CME FedWatch: rate probabilities — startup, then every 30 min

All data is persisted to the database and served from cache by the API layer.
"""

import asyncio
import hashlib
import logging
import threading
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("fomc.scheduler")

STATEMENTS_FETCH_HOUR = 15
NEWS_INTERVAL_SEC = 1800
RATE_FRIDAY_FETCH_HOUR = 10

_FOMC_MEETINGS = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-05-05", "2027-06-16",
    "2027-07-28", "2027-09-22", "2027-10-27", "2027-12-15",
]

# Post-meeting fetch offsets in hours
_POST_MEETING_OFFSETS_H = [1, 24, 72]


def _get_settings():
    """Late import to avoid circular dependency."""
    try:
        from app.core.config import settings
        return settings
    except ImportError:
        return None


async def _refresh_rates(db_url: str) -> int:
    """Refresh federal funds rate from FRED API (or hardcoded fallback)."""
    from data.fomc.rate_fetcher import refresh_rates

    s = _get_settings()
    fred_key = s.FRED_API_KEY if s else ""
    return await refresh_rates(db_url, fred_key)


async def _refresh_statements(db_url: str) -> int:
    """Run the FOMC statement loader (incremental — only new statements)."""
    from data.fomc.loader import run_loader

    return await run_loader(db_url, start_year=2020)


async def _refresh_news(db_url: str) -> int:
    """Fetch Fed/FOMC news via Google News RSS and persist to news_articles."""
    import xml.etree.ElementTree as ET

    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text as sa_text

    query = "Federal Reserve FOMC interest rate decision"
    url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("FOMC news RSS returned %d", resp.status_code)
            return 0
    except Exception:
        logger.warning("FOMC news RSS fetch failed", exc_info=True)
        return 0

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        logger.warning("FOMC news RSS parse failed")
        return 0

    articles = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        source_el = item.find("source")
        if title_el is None or not title_el.text:
            continue

        headline = title_el.text.strip()
        article_url = link_el.text.strip() if link_el is not None and link_el.text else None
        source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"

        pub_time = datetime.now(UTC)
        if pub_el is not None and pub_el.text:
            try:
                from email.utils import parsedate_to_datetime
                pub_time = parsedate_to_datetime(pub_el.text)
            except Exception:
                pass

        article_id = hashlib.md5(
            f"{headline}:{article_url}".encode()
        ).hexdigest()

        articles.append({
            "id": article_id,
            "time": pub_time,
            "ticker": "FOMC",
            "headline": headline,
            "source": source,
            "url": article_url,
            "raw_metadata": '{"category": "fomc"}',
        })

    if not articles:
        return 0

    engine = create_async_engine(db_url)
    upsert_sql = sa_text("""
        INSERT INTO news_articles (time, ticker, headline, source, url, raw_metadata)
        VALUES (:time, :ticker, :headline, :source, :url, :raw_metadata::jsonb)
        ON CONFLICT DO NOTHING
    """)

    try:
        async with engine.begin() as conn:
            for a in articles[:30]:
                await conn.execute(upsert_sql, {
                    "time": a["time"],
                    "ticker": a["ticker"],
                    "headline": a["headline"],
                    "source": a["source"],
                    "url": a["url"],
                    "raw_metadata": a["raw_metadata"],
                })
        return len(articles[:30])
    except Exception:
        logger.warning("FOMC news DB upsert failed", exc_info=True)
        return 0
    finally:
        await engine.dispose()


async def _refresh_fedwatch(db_url: str) -> int:
    """Fetch CME FedWatch probabilities and persist to fomc_rate_probabilities."""
    from data.fomc.fedwatch import fetch_fedwatch_probabilities
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text as sa_text

    probs = await fetch_fedwatch_probabilities()
    if not probs:
        return 0

    now = datetime.now(UTC)

    today_str = now.strftime("%Y-%m-%d")
    next_meeting = None
    for d in _FOMC_MEETINGS:
        if d >= today_str:
            next_meeting = d
            break

    engine = create_async_engine(db_url)
    upsert_sql = sa_text("""
        INSERT INTO fomc_rate_probabilities (time, meeting_date, target_rate_low, target_rate_high, probability)
        VALUES (:time, :meeting_date, :target_rate_low, :target_rate_high, :probability)
        ON CONFLICT (time, meeting_date, target_rate_low) DO UPDATE SET
            target_rate_high = EXCLUDED.target_rate_high,
            probability = EXCLUDED.probability
    """)

    try:
        async with engine.begin() as conn:
            for p in probs:
                meeting = p.get("meeting_date") or next_meeting
                if not meeting:
                    continue
                await conn.execute(upsert_sql, {
                    "time": now,
                    "meeting_date": meeting,
                    "target_rate_low": p["target_rate_low"],
                    "target_rate_high": p["target_rate_high"],
                    "probability": p["probability"],
                })
        return len(probs)
    except Exception:
        logger.warning("FedWatch DB upsert failed", exc_info=True)
        return 0
    finally:
        await engine.dispose()


def _should_fetch_rate(now_et) -> bool:
    """Check if we should fetch rates right now.

    Triggers:
    - Every Friday at RATE_FRIDAY_FETCH_HOUR ET
    - 1h, 24h, 72h after each FOMC meeting date (14:00 ET assumed release)
    """
    # Friday weekly fetch
    if now_et.weekday() == 4 and now_et.hour == RATE_FRIDAY_FETCH_HOUR:
        return True

    # Post-meeting triggers
    for meeting_str in _FOMC_MEETINGS:
        try:
            import zoneinfo
            et = zoneinfo.ZoneInfo("America/New_York")
            meeting_dt = datetime.strptime(meeting_str, "%Y-%m-%d").replace(
                hour=14, minute=0, tzinfo=et
            )
        except (ValueError, Exception):
            continue

        for offset_h in _POST_MEETING_OFFSETS_H:
            target = meeting_dt + timedelta(hours=offset_h)
            if abs((now_et - target).total_seconds()) < NEWS_INTERVAL_SEC:
                return True

    return False


def run_scheduler(stop_event: threading.Event, db_url: str) -> None:
    """Entry point for the background thread. Blocks until stop_event is set."""
    import zoneinfo

    et = zoneinfo.ZoneInfo("America/New_York")

    # ── Startup: fetch all four sources ──
    logger.info("fomc scheduler: startup — refreshing fed funds rate")
    try:
        count = asyncio.run(_refresh_rates(db_url))
        logger.info("fomc scheduler: rates — %d rows upserted", count)
    except Exception:
        logger.warning("fomc scheduler: rates startup failed", exc_info=True)

    logger.info("fomc scheduler: startup — refreshing statements")
    try:
        count = asyncio.run(_refresh_statements(db_url))
        logger.info("fomc scheduler: statements — %d upserted", count)
    except Exception:
        logger.warning("fomc scheduler: statements startup failed", exc_info=True)

    logger.info("fomc scheduler: startup — refreshing news")
    try:
        count = asyncio.run(_refresh_news(db_url))
        logger.info("fomc scheduler: news — %d articles stored", count)
    except Exception:
        logger.warning("fomc scheduler: news startup failed", exc_info=True)

    logger.info("fomc scheduler: startup — refreshing FedWatch")
    try:
        count = asyncio.run(_refresh_fedwatch(db_url))
        logger.info("fomc scheduler: FedWatch — %d probabilities stored", count)
    except Exception:
        logger.warning("fomc scheduler: FedWatch startup failed", exc_info=True)

    # ── Periodic loop (every 30 min) ──
    tick = 0
    statements_last_date = ""
    rate_last_key = ""

    while not stop_event.is_set():
        if stop_event.wait(timeout=NEWS_INTERVAL_SEC):
            break
        tick += 1

        now_et = datetime.now(et)

        # News: every tick (~30 min)
        try:
            count = asyncio.run(_refresh_news(db_url))
            if count:
                logger.info("fomc scheduler: news tick %d — %d articles", tick, count)
        except Exception:
            logger.warning("fomc scheduler: news tick %d failed", tick, exc_info=True)

        # FedWatch: every tick (~30 min)
        try:
            count = asyncio.run(_refresh_fedwatch(db_url))
            if count:
                logger.info("fomc scheduler: FedWatch tick %d — %d probs", tick, count)
        except Exception:
            logger.warning("fomc scheduler: FedWatch tick %d failed", tick, exc_info=True)

        # Fed funds rate: Friday + post-FOMC meeting triggers
        rate_key = f"{now_et.strftime('%Y-%m-%d')}:{now_et.hour}"
        if rate_key != rate_last_key and _should_fetch_rate(now_et):
            logger.info("fomc scheduler: rate refresh triggered")
            try:
                count = asyncio.run(_refresh_rates(db_url))
                logger.info("fomc scheduler: rates — %d rows", count)
                rate_last_key = rate_key
            except Exception:
                logger.warning("fomc scheduler: rate refresh failed", exc_info=True)

        # Statements: once daily at STATEMENTS_FETCH_HOUR ET (weekdays)
        today_key = now_et.strftime("%Y-%m-%d")
        if (
            now_et.weekday() < 5
            and now_et.hour == STATEMENTS_FETCH_HOUR
            and today_key != statements_last_date
        ):
            logger.info("fomc scheduler: daily statements refresh")
            try:
                count = asyncio.run(_refresh_statements(db_url))
                logger.info("fomc scheduler: statements — %d upserted", count)
                statements_last_date = today_key
            except Exception:
                logger.warning("fomc scheduler: statements daily failed", exc_info=True)
