"""News ingestion scheduler — runs as a backend lifespan thread.

Schedule:
  - Startup: ingest all hot tickers immediately
  - Tier-1 (MAG7 + top ETFs): every NEWS_TIER1_INTERVAL_MIN (default 5 min)
  - Tier-2 (rest of hot tickers): every NEWS_TIER2_INTERVAL_MIN (default 20 min)
"""

import asyncio
import logging
import threading
from collections.abc import Callable

from data.news.constants import TIER1_INTERVAL_SEC, TIER2_INTERVAL_SEC

logger = logging.getLogger("news.scheduler")


def run_scheduler(
    stop_event: threading.Event,
    db_url: str,
    on_new_articles: Callable[[], None] | None = None,
) -> None:
    """Entry point for the background thread. Blocks until stop_event is set.

    ``on_new_articles`` is invoked after any ingest that inserted new rows, so the
    backend can drop its in-memory hot-news cache and serve fresh articles immediately
    (the scheduler runs in the same process as the API).
    """
    from data.news.ingest import ingest_all, ingest_tier1, ingest_tier2

    tier2_every_n = max(1, round(TIER2_INTERVAL_SEC / TIER1_INTERVAL_SEC))

    def _notify(new_count: int) -> None:
        if new_count > 0 and on_new_articles is not None:
            try:
                on_new_articles()
            except Exception:
                logger.warning("news scheduler: cache-invalidation callback failed", exc_info=True)

    logger.info(
        "news scheduler: tier-1 every %ds, tier-2 every %d ticks (%ds)",
        TIER1_INTERVAL_SEC, tier2_every_n, TIER2_INTERVAL_SEC,
    )

    # Startup: fetch everything once
    logger.info("news scheduler: initial full ingest on startup")
    try:
        count = asyncio.run(ingest_all(db_url))
        logger.info("news scheduler: startup ingest done — %d new articles", count)
        _notify(count)
    except Exception:
        logger.warning("news scheduler: startup ingest failed", exc_info=True)

    tick = 0
    while not stop_event.is_set():
        if stop_event.wait(timeout=TIER1_INTERVAL_SEC):
            break

        tick += 1
        try:
            if tick % tier2_every_n == 0:
                logger.info("news scheduler: tier-1 + tier-2 cycle (tick %d)", tick)
                count1 = asyncio.run(ingest_tier1(db_url))
                count2 = asyncio.run(ingest_tier2(db_url))
                logger.info("news scheduler: tier-1=%d, tier-2=%d new articles", count1, count2)
                _notify(count1 + count2)
            else:
                logger.info("news scheduler: tier-1 cycle (tick %d)", tick)
                count = asyncio.run(ingest_tier1(db_url))
                logger.info("news scheduler: tier-1=%d new articles", count)
                _notify(count)
        except Exception:
            logger.warning("news scheduler: cycle %d failed", tick, exc_info=True)
