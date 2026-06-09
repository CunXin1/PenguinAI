"""Startup warmup — fill gaps in market_data_1min for core symbols.

On startup (or reconnect), the most recent 1-min bars may be hours or days
old.  This fetches the latest bars from Massive for the core watchlist so
charts are immediately current before the live streams take over.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from data.ingestion.realtime.massive_poller import poll_symbol

logger = logging.getLogger("realtime.warmup")

_STALE_THRESHOLD = timedelta(minutes=15)
_BATCH_SQL = text(
    "SELECT ticker, max(time) AS latest FROM market_data_1min "
    "WHERE ticker = ANY(:syms) GROUP BY ticker"
)


async def warmup_core(engine, settings, symbols: list[str]) -> int:
    """Fetch recent 1-min bars for ``symbols`` from Massive, filling the gap
    since the last shutdown.  Symbols whose latest bar is <15 min old are
    skipped.  Returns total bars written."""
    if not settings.MASSIVE_API_KEY:
        logger.info("warmup skipped: no MASSIVE_API_KEY")
        return 0
    if not symbols:
        return 0

    cutoff = datetime.now(UTC) - _STALE_THRESHOLD
    async with engine.connect() as conn:
        rows = (await conn.execute(_BATCH_SQL, {"syms": [s.upper() for s in symbols]})).mappings().all()
    fresh = {r["ticker"] for r in rows if r["latest"] and r["latest"] >= cutoff}
    stale = [s for s in symbols if s.upper() not in fresh]

    if not stale:
        logger.info("warmup: all %d core symbols are fresh — skipping", len(symbols))
        return 0

    logger.info(
        "warmup: %d/%d core symbols are stale — fetching from Massive",
        len(stale), len(symbols),
    )

    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    sem = asyncio.Semaphore(8)
    total = 0

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {key}"}
    ) as client:

        async def one(sym: str) -> int:
            async with sem:
                try:
                    n = await poll_symbol(engine, client, base, key, sym)
                    return max(n, 0)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("warmup %s: %r", sym, exc)
                    return 0

        results = await asyncio.gather(*(one(s) for s in stale))
        total = sum(results)

    logger.info("warmup complete: %d bars across %d symbols", total, len(stale))
    return total
