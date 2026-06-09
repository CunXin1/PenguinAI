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
import json
import logging
import signal
import sys
from time import monotonic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from data.ingestion.realtime import close_30min, finnhub_ws, ibkr_service, massive_poller
from data.ingestion.realtime.config import IBKR_SYMBOLS, RealtimeSettings
from data.ingestion.realtime.finnhub_ws import CrossValidator
from data.ingestion.realtime.warmup import warmup_core

logger = logging.getLogger("realtime.supervisor")

_MAX_BACKOFF = 300.0  # 5 min cap on restart delay
_INITIAL_BACKOFF = 2.0


async def _distinct_1min_tickers(engine) -> set[str]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT DISTINCT ticker FROM market_data_1min"))).scalars().all()
    return {t.upper() for t in rows}


def _service_factory(
    name: str, engine, settings, stop, *,
    ibkr_symbols, poll_symbols, watched_symbols, cross_validator,
):
    """Return the coroutine for a named service."""
    if name == "ibkr":
        return ibkr_service.run(engine, settings, stop, ibkr_symbols, cross_validator)
    if name == "massive":
        return massive_poller.run(engine, settings, stop, poll_symbols)
    if name == "finnhub":
        return finnhub_ws.run(engine, settings, stop, ibkr_symbols, cross_validator)
    if name == "close30m":
        return close_30min.run(engine, settings, stop, watched_symbols)
    raise ValueError(f"unknown service: {name}")


class _ServiceState:
    __slots__ = ("name", "task", "backoff", "restarts", "last_start")

    def __init__(self, name: str, task: asyncio.Task):
        self.name = name
        self.task = task
        self.backoff = _INITIAL_BACKOFF
        self.restarts = 0
        self.last_start = monotonic()


def _health_snapshot(services: dict[str, _ServiceState]) -> dict:
    """JSON-serialisable health dict, printed to stdout so the FastAPI watchdog can read it."""
    now = monotonic()
    svc = {}
    for name, st in services.items():
        done = st.task.done()
        svc[name] = {
            "alive": not done,
            "restarts": st.restarts,
            "uptime_s": round(now - st.last_start, 1) if not done else 0,
        }
    return {"services": svc}


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

    ibkr_set = {x.upper() for x in IBKR_SYMBOLS} if s.IBKR_ENABLED else set()

    try:
        await warmup_core(engine, s, IBKR_SYMBOLS)
    except Exception as exc:  # noqa: BLE001
        logger.error("startup warmup failed: %r (continuing)", exc)

    poll_symbols = sorted(await _distinct_1min_tickers(engine) - ibkr_set)
    xv = CrossValidator()

    async def watched_symbols() -> list[str]:
        return sorted((await _distinct_1min_tickers(engine)) | ibkr_set)

    factory_kw = {
        "ibkr_symbols": IBKR_SYMBOLS, "poll_symbols": poll_symbols,
        "watched_symbols": watched_symbols, "cross_validator": xv,
    }

    services: dict[str, _ServiceState] = {}
    svc_names = []
    if s.IBKR_ENABLED:
        svc_names.append("ibkr")
    if s.FINNHUB_WS_ENABLED and s.FINNHUB_API_KEY:
        svc_names.append("finnhub")
    svc_names += ["massive", "close30m"]

    for name in svc_names:
        coro = _service_factory(name, engine, s, stop, **factory_kw)
        task = asyncio.create_task(coro, name=name)
        services[name] = _ServiceState(name, task)

    logger.info(
        "supervisor up: ibkr=%s(%d) finnhub=%s massive_poll=%d",
        s.IBKR_ENABLED, len(IBKR_SYMBOLS),
        s.FINNHUB_WS_ENABLED and bool(s.FINNHUB_API_KEY), len(poll_symbols),
    )

    # Periodically print health to stdout so the FastAPI watchdog can read it.
    async def _health_reporter():
        while not stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=30.0)
            snap = _health_snapshot(services)
            sys.stdout.write(f"HEALTH:{json.dumps(snap)}\n")
            sys.stdout.flush()

    health_task = asyncio.create_task(_health_reporter(), name="health")

    try:
        stop_task = asyncio.create_task(stop.wait(), name="stop-sentinel")
        while not stop.is_set():
            live_tasks = {st.task: st for st in services.values() if not st.task.done()}
            if not live_tasks:
                await asyncio.sleep(1.0)
                continue

            done, _ = await asyncio.wait(
                [*live_tasks.keys(), stop_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if stop.is_set():
                break

            for finished in done:
                st = live_tasks.get(finished)
                if st is None:
                    continue
                exc = finished.exception() if not finished.cancelled() else None
                if exc:
                    logger.error("service %s crashed: %r — restarting in %.0fs", st.name, exc, st.backoff)
                else:
                    logger.warning("service %s exited cleanly — restarting in %.0fs", st.name, st.backoff)

                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=st.backoff)
                if stop.is_set():
                    break

                st.backoff = min(st.backoff * 2, _MAX_BACKOFF)
                st.restarts += 1
                coro = _service_factory(st.name, engine, s, stop, **factory_kw)
                st.task = asyncio.create_task(coro, name=st.name)
                st.last_start = monotonic()
                logger.info("service %s restarted (attempt #%d)", st.name, st.restarts)
    finally:
        logger.info("supervisor stopping ...")
        stop_task.cancel()
        health_task.cancel()
        for st in services.values():
            st.task.cancel()
        await asyncio.gather(
            stop_task, health_task, *(st.task for st in services.values()), return_exceptions=True
        )
        await engine.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
