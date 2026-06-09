"""News ingestion scheduler — runs as a backend lifespan thread.

Schedule:
  - Startup: ingest all hot tickers immediately
  - Tier-1 (MAG7 + top ETFs): every 15 min
  - Tier-2 (rest of hot tickers): every 60 min

The scheduler alternates between tier-1 and tier-2 cycles. Tier-1 runs on every
tick (15 min), tier-2 runs on every 4th tick (60 min).
"""

import asyncio
import logging
import threading

from data.news.constants import TIER1_INTERVAL_SEC

logger = logging.getLogger("news.scheduler")


def run_scheduler(stop_event: threading.Event, db_url: str) -> None:
    """Entry point for the background thread. Blocks until stop_event is set."""
    from data.news.ingest import ingest_all, ingest_tier1, ingest_tier2

    # Startup: fetch everything once
    logger.info("news scheduler: initial full ingest on startup")
    try:
        count = asyncio.run(ingest_all(db_url))
        logger.info("news scheduler: startup ingest done — %d new articles", count)
    except Exception:
        logger.warning("news scheduler: startup ingest failed", exc_info=True)

    tick = 0
    while not stop_event.is_set():
        if stop_event.wait(timeout=TIER1_INTERVAL_SEC):
            break

        tick += 1
        try:
            # Tier-1 every tick (15 min), tier-2 every 4th tick (60 min)
            if tick % 4 == 0:
                logger.info("news scheduler: tier-1 + tier-2 cycle")
                count1 = asyncio.run(ingest_tier1(db_url))
                count2 = asyncio.run(ingest_tier2(db_url))
                logger.info("news scheduler: tier-1=%d, tier-2=%d new articles", count1, count2)
            else:
                logger.info("news scheduler: tier-1 cycle")
                count = asyncio.run(ingest_tier1(db_url))
                logger.info("news scheduler: tier-1=%d new articles", count)
        except Exception:
            logger.warning("news scheduler: cycle %d failed", tick, exc_info=True)
