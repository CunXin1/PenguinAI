"""IBKR 1-min stream for the realtime watchlist (10 ETF + 40 stocks) →
market_data_1min (source='ibkr'), recomputing indicators after each finalized
minute.

Mirrors data/ingestion/ibkr_stream.py's proven pipeline (ib_async
reqHistoricalDataAsync keepUpToDate → queue → batched upsert) and adds a
debounced per-ticker indicator refresh. Needs TWS/Gateway running + market-data
subscriptions; ib_async is imported lazily so this module loads without it (the
supervisor then runs Massive-only).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime

from sqlalchemy import text

from data.ingestion.realtime.indicators import update_indicators

logger = logging.getLogger("realtime.ibkr")

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


def _make_handler(ticker: str, queue: asyncio.Queue):
    def _on_update(bars, has_new_bar: bool) -> None:  # noqa: FBT001 (ib_async signature)
        if not bars:
            return
        recent = bars[-2:] if (has_new_bar and len(bars) >= 2) else bars[-1:]
        for b in recent:
            row = _bar_to_row(ticker, b)
            if row is not None:
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(row)
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


async def run(engine, settings, stop: asyncio.Event, symbols: list[str]) -> None:
    try:
        from ib_async import IB, Stock
    except ModuleNotFoundError:
        logger.warning("ib_async not installed — IBKR stream disabled (Massive-only)")
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=20_000)
    dirty: set[str] = set()
    consumer = asyncio.create_task(_consumer(engine, queue, dirty))
    refresher = asyncio.create_task(_indicator_refresher(engine, dirty, stop))
    ib = IB()
    try:
        while not stop.is_set():
            try:
                logger.info("IBKR connect %s:%s clientId=%s", settings.IBKR_HOST, settings.IBKR_PORT, settings.IBKR_CLIENT_ID)
                await ib.connectAsync(
                    settings.IBKR_HOST, settings.IBKR_PORT,
                    clientId=settings.IBKR_CLIENT_ID, timeout=20.0, readonly=True,
                )
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
                            with contextlib.suppress(asyncio.QueueFull):
                                queue.put_nowait(row)
                    bars.updateEvent += _make_handler(tk, queue)
                    dirty.add(tk)
                logger.info("IBKR streaming %d symbols → market_data_1min", len(symbols))
                while ib.isConnected() and not stop.is_set():
                    await asyncio.sleep(1.0)
            except Exception as exc:  # noqa: BLE001 — reconnect on any IB/socket error
                logger.error("IBKR stream error: %r", exc)
            finally:
                if ib.isConnected():
                    ib.disconnect()
            if not stop.is_set():
                logger.info("IBKR reconnecting in 10s ...")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=10.0)
    finally:
        consumer.cancel()
        refresher.cancel()
        await asyncio.gather(consumer, refresher, return_exceptions=True)
