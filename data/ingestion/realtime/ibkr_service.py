"""IBKR 1-min stream for the realtime watchlist (10 ETF + 40 stocks) →
market_data_1min (source='ibkr'), recomputing indicators after each finalized
minute.

Mirrors data/ingestion/ibkr_stream.py's proven pipeline (ib_async
reqHistoricalDataAsync keepUpToDate → queue → batched upsert) and adds a
debounced per-ticker indicator refresh. Needs TWS/Gateway running + market-data
subscriptions; ib_async is imported lazily so this module loads without it (the
supervisor then runs Massive-only).

Zombie prevention strategy (multi-layer):
  1. Error codes 1100/1101/1102/2108 → immediate detection of connectivity loss
  2. reqCurrentTime() heartbeat every 30s → detect silent connection death
  3. Global last_bar_at timeout (120s) → catch-all if layers 1-2 somehow miss it
  4. On 1101 (data lost) → full resubscribe of all keepUpToDate streams
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime
from time import monotonic

from sqlalchemy import text

from data.ingestion.realtime.indicators import update_indicators

logger = logging.getLogger("realtime.ibkr")

_dropped_bars = 0
_ZOMBIE_TIMEOUT = 120.0
_HEARTBEAT_INTERVAL = 30.0
_HEARTBEAT_TIMEOUT = 10.0
_DATA_STABLE_SECS = 300.0  # 5 min of data flowing before resetting backoff

_UPSERT_SQL = text(
    """
    INSERT INTO market_data_1min (time, ticker, open, high, low, close, volume, vwap, source)
    VALUES (:time, :ticker, :open, :high, :low, :close, :volume, :vwap, 'ibkr')
    ON CONFLICT (ticker, time) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
        close = EXCLUDED.close, volume = EXCLUDED.volume, vwap = EXCLUDED.vwap,
        source = 'ibkr'
    """
)


def _to_utc(bar_date: object) -> datetime | None:
    if isinstance(bar_date, bool):
        return None
    if isinstance(bar_date, (int, float)):
        return datetime.fromtimestamp(bar_date, tz=UTC)
    if isinstance(bar_date, datetime):
        return bar_date.astimezone(UTC) if bar_date.tzinfo else bar_date.replace(tzinfo=UTC)
    if isinstance(bar_date, date):
        return datetime(bar_date.year, bar_date.month, bar_date.day, tzinfo=UTC)
    with contextlib.suppress(TypeError, ValueError):
        return datetime.fromisoformat(str(bar_date)).astimezone(UTC)
    return None


def _bar_to_row(ticker: str, bar: object) -> dict | None:
    t = _to_utc(getattr(bar, "date", None))
    o, h, low, c = (getattr(bar, k, None) for k in ("open", "high", "low", "close"))
    if t is None or None in (o, h, low, c) or o <= 0 or h <= 0:
        return None
    raw_vol = getattr(bar, "volume", 0) or 0
    avg = getattr(bar, "average", None)
    return {
        "time": t, "ticker": ticker,
        "open": float(o), "high": float(h), "low": float(low), "close": float(c),
        "volume": int(raw_vol) if raw_vol > 0 else 0,
        "vwap": float(avg) if avg not in (None, -1, -1.0) else None,
    }


def _make_handler(ticker: str, queue: asyncio.Queue, last_bar_at: dict, cross_validator=None):
    def _on_update(bars, has_new_bar: bool) -> None:  # noqa: FBT001 (ib_async signature)
        global _dropped_bars  # noqa: PLW0603
        if not bars:
            return
        last_bar_at["t"] = monotonic()
        recent = bars[-2:] if (has_new_bar and len(bars) >= 2) else bars[-1:]
        for b in recent:
            row = _bar_to_row(ticker, b)
            if row is not None:
                if cross_validator is not None:
                    cross_validator.update_ibkr(ticker, row["close"])
                try:
                    queue.put_nowait(row)
                except asyncio.QueueFull:
                    _dropped_bars += 1
                    if _dropped_bars % 100 == 1:
                        logger.warning(
                            "queue full — dropped bar for %s (total dropped: %d)", ticker, _dropped_bars
                        )
    return _on_update


async def _consumer(engine, queue: asyncio.Queue, dirty: set[str]) -> None:
    """Drain the queue, batch-upsert, and mark touched tickers for indicator refresh."""
    while True:
        first = await queue.get()
        batch = [first]
        while len(batch) < 500:
            try:
                batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        try:
            async with engine.begin() as conn:
                await conn.execute(_UPSERT_SQL, batch)
            dirty.update(r["ticker"] for r in batch)
        except Exception as exc:  # noqa: BLE001 — keep the consumer alive
            logger.error("ibkr upsert failed (%d rows): %r", len(batch), exc)


async def _indicator_refresher(engine, dirty: set[str], stop: asyncio.Event) -> None:
    """Every few seconds, recompute indicators for tickers that got new bars."""
    while not stop.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        todo = list(dirty)
        dirty.clear()
        for tk in todo:
            try:
                await update_indicators(engine, tk, tail=6)
            except Exception as exc:  # noqa: BLE001
                logger.error("ibkr indicator refresh %s: %r", tk, exc)


async def _subscribe_all(ib, symbols: list[str], queue: asyncio.Queue, last_bar_at: dict, dirty: set):
    """Subscribe to keepUpToDate 1-min bars for all symbols. Returns count of successful subs."""
    from ib_async import Stock

    subscribed = 0
    for tk in symbols:
        contract = Stock(tk, "SMART", "USD")
        if not await ib.qualifyContractsAsync(contract):
            logger.warning("could not qualify %s — skipping", tk)
            continue
        bars = await ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr="3600 S",
            barSizeSetting="1 min", whatToShow="TRADES",
            useRTH=False, formatDate=2, keepUpToDate=True,
        )
        for b in bars:
            row = _bar_to_row(tk, b)
            if row is not None:
                try:
                    queue.put_nowait(row)
                except asyncio.QueueFull:
                    global _dropped_bars  # noqa: PLW0603
                    _dropped_bars += 1
        bars.updateEvent += _make_handler(tk, queue, last_bar_at)
        dirty.add(tk)
        subscribed += 1
    return subscribed


async def _heartbeat(ib) -> bool:
    """Ping IBKR with reqCurrentTime. Returns True if alive."""
    try:
        await asyncio.wait_for(ib.reqCurrentTimeAsync(), timeout=_HEARTBEAT_TIMEOUT)
        return True
    except (asyncio.TimeoutError, Exception):
        return False


async def run(engine, settings, stop: asyncio.Event, symbols: list[str]) -> None:
    try:
        from ib_async import IB
    except ModuleNotFoundError:
        logger.warning("ib_async not installed — IBKR stream disabled (Massive-only)")
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=20_000)
    dirty: set[str] = set()
    consumer = asyncio.create_task(_consumer(engine, queue, dirty))
    refresher = asyncio.create_task(_indicator_refresher(engine, dirty, stop))
    ib = IB()
    ib.RequestTimeout = 30
    backoff = 10.0
    max_backoff = 300.0

    force_reconnect = asyncio.Event()
    need_resubscribe = asyncio.Event()

    def _on_error(reqId: int, errorCode: int, errorString: str, contract=None):
        if errorCode == 1100:
            logger.warning("IBKR connectivity lost (code 1100) — waiting for restore")
        elif errorCode == 1101:
            logger.warning("IBKR connectivity restored, DATA LOST (1101) — will resubscribe")
            need_resubscribe.set()
        elif errorCode == 1102:
            logger.info("IBKR connectivity restored, data maintained (1102)")
        elif errorCode == 2108:
            logger.warning("IBKR market data farm inactive (2108): %s — possible zombie", errorString)
            force_reconnect.set()
        elif errorCode in (2103, 2105, 2107):
            logger.warning("IBKR data farm disconnected (code %d): %s", errorCode, errorString)

    def _on_disconnect():
        logger.warning("IBKR disconnectedEvent fired")
        force_reconnect.set()

    try:
        while not stop.is_set():
            force_reconnect.clear()
            need_resubscribe.clear()
            try:
                logger.info(
                    "IBKR connect %s:%s clientId=%s",
                    settings.IBKR_HOST, settings.IBKR_PORT, settings.IBKR_CLIENT_ID,
                )
                await ib.connectAsync(
                    settings.IBKR_HOST, settings.IBKR_PORT,
                    clientId=settings.IBKR_CLIENT_ID, timeout=20.0, readonly=True,
                )
                ib.errorEvent += _on_error
                ib.disconnectedEvent += _on_disconnect

                last_bar_at: dict = {"t": monotonic()}
                n = await _subscribe_all(ib, symbols, queue, last_bar_at, dirty)
                logger.info("IBKR streaming %d/%d symbols → market_data_1min", n, len(symbols))

                connected_at = monotonic()
                last_heartbeat = monotonic()
                heartbeat_failures = 0

                while ib.isConnected() and not stop.is_set() and not force_reconnect.is_set():
                    # Handle 1101: data lost → resubscribe without full reconnect
                    if need_resubscribe.is_set():
                        need_resubscribe.clear()
                        logger.info("Resubscribing all keepUpToDate streams after 1101")
                        for bars_obj in list(getattr(ib.wrapper, "_bars", {}).values()):
                            with contextlib.suppress(Exception):
                                ib.cancelHistoricalData(bars_obj)
                        await asyncio.sleep(2.0)
                        last_bar_at["t"] = monotonic()
                        n = await _subscribe_all(ib, symbols, queue, last_bar_at, dirty)
                        logger.info("Resubscribed %d/%d symbols", n, len(symbols))
                        connected_at = monotonic()

                    await asyncio.sleep(1.0)
                    now = monotonic()

                    # Layer 1: periodic heartbeat via reqCurrentTime
                    if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                        last_heartbeat = now
                        alive = await _heartbeat(ib)
                        if not alive:
                            heartbeat_failures += 1
                            logger.warning(
                                "IBKR heartbeat failed (%d consecutive)", heartbeat_failures
                            )
                            if heartbeat_failures >= 3:
                                logger.error("IBKR heartbeat failed 3x — forcing reconnect")
                                break
                        else:
                            heartbeat_failures = 0

                    # Layer 2: global data freshness check
                    idle = now - last_bar_at["t"]
                    if idle > _ZOMBIE_TIMEOUT:
                        logger.warning(
                            "IBKR zombie: no data for %.0fs — forcing reconnect", idle
                        )
                        break

                    # Only reset backoff after sustained data flow
                    if now - connected_at > _DATA_STABLE_SECS and backoff > 10.0:
                        backoff = 10.0
                        logger.info("IBKR connection stable for 5min — backoff reset")

            except Exception as exc:  # noqa: BLE001
                logger.error("IBKR stream error: %r", exc)
            finally:
                ib.errorEvent -= _on_error
                ib.disconnectedEvent -= _on_disconnect
                if ib.isConnected():
                    ib.disconnect()

            if not stop.is_set():
                logger.info("IBKR reconnecting in %.0fs ...", backoff)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                backoff = min(backoff * 2, max_backoff)
    finally:
        consumer.cancel()
        refresher.cancel()
        await asyncio.gather(consumer, refresher, return_exceptions=True)
