"""Realtime ingestion supervisor — one asyncio process running:
  • IBKR 1-min stream for the watchlist (10 ETF + 40 stocks)  → market_data_1min
  • Massive 1-min poller for the rest of the watched 1-min universe
  • after-close / post-market 30-min refresh → bars_30m (Yahoo fallback)
all writing indicators alongside the bars.

Spawned by the FastAPI lifespan (backend/app/main.py) when REALTIME_ENABLED is
true, so the live data layer comes up with the backend. Also runnable directly:
    backend/.venv/Scripts/python -m data.ingestion.realtime.supervisor
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from data.ingestion.realtime import close_30min, ibkr_service, massive_poller
from data.ingestion.realtime.config import IBKR_SYMBOLS, RealtimeSettings

logger = logging.getLogger("realtime.supervisor")


async def _distinct_1min_tickers(engine) -> set[str]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT DISTINCT ticker FROM market_data_1min"))).scalars().all()
    return {t.upper() for t in rows}


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    s = RealtimeSettings()
    if not s.REALTIME_ENABLED:
        logger.info("REALTIME_ENABLED=false — supervisor exiting")
        return

    engine = create_async_engine(s.DATABASE_URL, pool_size=12, max_overflow=8)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_ in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig_ is not None:
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig_, stop.set)

    # Massive excludes the IBKR set ONLY when IBKR is actually streaming them;
    # with IBKR off, Massive must cover everything so nothing goes stale.
    ibkr_set = {x.upper() for x in IBKR_SYMBOLS} if s.IBKR_ENABLED else set()
    poll_symbols = sorted(await _distinct_1min_tickers(engine) - ibkr_set)

    async def watched_symbols() -> list[str]:
        # 30-min refresh covers everything we hold 1-min data for (IBKR + polled)
        return sorted((await _distinct_1min_tickers(engine)) | ibkr_set)

    tasks: list[asyncio.Task] = []
    if s.IBKR_ENABLED:
        tasks.append(asyncio.create_task(ibkr_service.run(engine, s, stop, IBKR_SYMBOLS), name="ibkr"))
    tasks.append(asyncio.create_task(massive_poller.run(engine, s, stop, poll_symbols), name="massive"))
    tasks.append(asyncio.create_task(close_30min.run(engine, s, stop, watched_symbols), name="close30m"))

    logger.info(
        "supervisor up: ibkr=%s(%d) massive_poll=%d", s.IBKR_ENABLED, len(IBKR_SYMBOLS), len(poll_symbols)
    )
    try:
        await stop.wait()
    finally:
        logger.info("supervisor stopping ...")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
