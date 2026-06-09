"""Background scheduler for Fear & Greed + VIX/VVIX.

Startup fetch, then refresh on a fixed interval. CNN updates the index several
times during market hours; CBOE history changes once per day after the close —
a single hourly refresh covers both cheaply.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading

from .loader import run_loader

logger = logging.getLogger(__name__)


def run_scheduler(stop_event: threading.Event, db_url: str) -> None:
    """Entry point for the background thread. Blocks until ``stop_event`` is set."""
    interval_min = int(os.getenv("FEAR_GREED_REFRESH_MIN", "60"))
    interval_sec = max(60, interval_min * 60)

    logger.info("fear&greed scheduler: startup fetch")
    try:
        n = asyncio.run(run_loader(db_url))
        logger.info("fear&greed scheduler: startup — %d rows", n)
    except Exception:
        logger.warning("fear&greed scheduler: startup failed", exc_info=True)

    while not stop_event.is_set():
        if stop_event.wait(timeout=interval_sec):
            break
        try:
            n = asyncio.run(run_loader(db_url))
            logger.info("fear&greed scheduler: refresh — %d rows", n)
        except Exception:
            logger.warning("fear&greed scheduler: refresh failed", exc_info=True)
