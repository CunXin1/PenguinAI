"""Finnhub WebSocket — real-time trade ticks aggregated into 1-min OHLCV bars.

Runs alongside IBKR (not as a fallback). Both sources write to market_data_1min
concurrently; the upsert's ON CONFLICT keeps whichever row is freshest. A shared
CrossValidator compares the two feeds and flags whichever one goes stale.

Finnhub free tier: real-time US SIP trades, up to 50 WebSocket symbols.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import text

from data.ingestion.realtime.indicators import update_indicators

logger = logging.getLogger("realtime.finnhub")

_UPSERT_SQL = text(
    """
    INSERT INTO market_data_1min (time, ticker, open, high, low, close, volume, source)
    VALUES (:time, :ticker, :open, :high, :low, :close, :volume, 'finnhub')
    ON CONFLICT (ticker, time) DO UPDATE SET
        open   = CASE WHEN EXCLUDED.source = 'finnhub' AND market_data_1min.source = 'finnhub'
                      THEN EXCLUDED.open ELSE market_data_1min.open END,
        high   = GREATEST(market_data_1min.high, EXCLUDED.high),
        low    = LEAST(market_data_1min.low, EXCLUDED.low),
        close  = EXCLUDED.close,
        volume = GREATEST(market_data_1min.volume, EXCLUDED.volume),
        source = CASE WHEN market_data_1min.source = 'ibkr' THEN 'ibkr' ELSE 'finnhub' END
    """
)


class _BarAccumulator:
    """Accumulate trade ticks into 1-min OHLCV bars in memory."""

    __slots__ = ("bars", "_lock")

    def __init__(self):
        self.bars: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    def _bar_key(self, ticker: str, ts: datetime) -> str:
        minute = ts.replace(second=0, microsecond=0)
        return f"{ticker}:{minute.isoformat()}"

    async def add_tick(self, ticker: str, price: float, volume: float, ts: datetime):
        minute = ts.replace(second=0, microsecond=0)
        key = self._bar_key(ticker, ts)
        async with self._lock:
            bar = self.bars.get(key)
            if bar is None:
                self.bars[key] = {
                    "time": minute, "ticker": ticker,
                    "open": price, "high": price, "low": price, "close": price,
                    "volume": int(volume),
                }
            else:
                bar["high"] = max(bar["high"], price)
                bar["low"] = min(bar["low"], price)
                bar["close"] = price
                bar["volume"] += int(volume)

    async def flush_completed(self, now: datetime) -> list[dict]:
        """Return and remove all bars whose minute is strictly before `now`'s minute."""
        cutoff = now.replace(second=0, microsecond=0)
        async with self._lock:
            ready = []
            stale_keys = []
            for key, bar in self.bars.items():
                if bar["time"] < cutoff:
                    ready.append(bar)
                    stale_keys.append(key)
            for k in stale_keys:
                del self.bars[k]
        return ready

    def latest_prices(self) -> dict[str, tuple[float, float]]:
        """Return {ticker: (last_price, monotonic_time)} from in-progress bars."""
        result = {}
        for bar in self.bars.values():
            result[bar["ticker"]] = (bar["close"], monotonic())
        return result


class CrossValidator:
    """Compare IBKR and Finnhub price feeds to detect zombie sources."""

    PRICE_DIVERGE_PCT = 2.0
    STALE_SECONDS = 120.0

    def __init__(self):
        self.ibkr_prices: dict[str, tuple[float, float]] = {}
        self.finnhub_prices: dict[str, tuple[float, float]] = {}
        self.ibkr_zombie_symbols: set[str] = set()
        self.finnhub_zombie_symbols: set[str] = set()

    def update_ibkr(self, ticker: str, price: float):
        self.ibkr_prices[ticker] = (price, monotonic())

    def update_finnhub(self, ticker: str, price: float):
        self.finnhub_prices[ticker] = (price, monotonic())

    def check(self) -> dict:
        """Run cross-validation. Returns a summary dict."""
        now = monotonic()
        ibkr_stale = set()
        finnhub_stale = set()
        diverged = set()

        all_tickers = set(self.ibkr_prices) | set(self.finnhub_prices)
        for tk in all_tickers:
            ibkr = self.ibkr_prices.get(tk)
            fh = self.finnhub_prices.get(tk)

            ibkr_age = (now - ibkr[1]) if ibkr else float("inf")
            fh_age = (now - fh[1]) if fh else float("inf")

            if ibkr_age > self.STALE_SECONDS and fh_age < self.STALE_SECONDS:
                ibkr_stale.add(tk)
            elif fh_age > self.STALE_SECONDS and ibkr_age < self.STALE_SECONDS:
                finnhub_stale.add(tk)

            if ibkr and fh and ibkr_age < 60 and fh_age < 60:
                mid = (ibkr[0] + fh[0]) / 2.0
                if mid > 0:
                    pct_diff = abs(ibkr[0] - fh[0]) / mid * 100.0
                    if pct_diff > self.PRICE_DIVERGE_PCT:
                        diverged.add(tk)

        self.ibkr_zombie_symbols = ibkr_stale
        self.finnhub_zombie_symbols = finnhub_stale
        return {
            "ibkr_stale": sorted(ibkr_stale),
            "finnhub_stale": sorted(finnhub_stale),
            "price_diverged": sorted(diverged),
        }


async def run(
    engine,
    settings,
    stop: asyncio.Event,
    symbols: list[str],
    cross_validator: CrossValidator,
) -> None:
    """Connect to Finnhub WebSocket, aggregate ticks → 1-min bars, write to DB."""
    if not settings.FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY empty — Finnhub WS disabled")
        return

    try:
        import websockets
    except ModuleNotFoundError:
        logger.warning("websockets package not installed — Finnhub WS disabled")
        return

    import json

    url = f"wss://ws.finnhub.io?token={settings.FINNHUB_API_KEY}"
    acc = _BarAccumulator()
    dirty: set[str] = set()
    backoff = 2.0
    max_backoff = 120.0

    async def _flush_loop():
        """Every 5s, flush completed bars to DB and refresh indicators."""
        while not stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            now = datetime.now(UTC)
            bars = await acc.flush_completed(now)
            if not bars:
                continue
            try:
                async with engine.begin() as conn:
                    await conn.execute(_UPSERT_SQL, bars)
                dirty.update(b["ticker"] for b in bars)
                logger.debug("finnhub flush: %d bars", len(bars))
            except Exception as exc:  # noqa: BLE001
                logger.error("finnhub upsert failed (%d bars): %r", len(bars), exc)

    async def _indicator_loop():
        """Recompute indicators for tickers that got Finnhub bars."""
        while not stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=10.0)
            todo = list(dirty)
            dirty.clear()
            for tk in todo:
                try:
                    await update_indicators(engine, tk, tail=6)
                except Exception as exc:  # noqa: BLE001
                    logger.error("finnhub indicator refresh %s: %r", tk, exc)

    async def _validate_loop():
        """Every 30s, run cross-validation and log anomalies."""
        while not stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=30.0)
            for _tk, bar in list(acc.bars.items()):
                cross_validator.update_finnhub(bar["ticker"], bar["close"])
            result = cross_validator.check()
            if result["ibkr_stale"]:
                logger.warning(
                    "CROSS-VALIDATE: IBKR stale for %d symbols (Finnhub live): %s",
                    len(result["ibkr_stale"]), result["ibkr_stale"][:10],
                )
            if result["finnhub_stale"]:
                logger.warning(
                    "CROSS-VALIDATE: Finnhub stale for %d symbols (IBKR live): %s",
                    len(result["finnhub_stale"]), result["finnhub_stale"][:10],
                )
            if result["price_diverged"]:
                logger.error(
                    "CROSS-VALIDATE: price divergence >%.1f%% on %s",
                    CrossValidator.PRICE_DIVERGE_PCT, result["price_diverged"][:10],
                )

    flush_task = asyncio.create_task(_flush_loop(), name="fh-flush")
    indicator_task = asyncio.create_task(_indicator_loop(), name="fh-indicators")
    validate_task = asyncio.create_task(_validate_loop(), name="fh-validate")

    try:
        while not stop.is_set():
            try:
                logger.info("Finnhub WS connecting (%d symbols)...", len(symbols))
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    for sym in symbols:
                        await ws.send(json.dumps({"type": "subscribe", "symbol": sym}))
                    logger.info("Finnhub WS subscribed to %d symbols", len(symbols))
                    backoff = 2.0

                    async for raw in ws:
                        if stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("type") != "trade":
                            continue
                        for trade in msg.get("data", []):
                            sym = trade.get("s")
                            price = trade.get("p")
                            vol = trade.get("v", 0)
                            ts_ms = trade.get("t")
                            if not sym or not price or not ts_ms:
                                continue
                            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
                            await acc.add_tick(sym, float(price), float(vol), ts)
                            cross_validator.update_finnhub(sym, float(price))

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Finnhub WS error: %r", exc)

            if not stop.is_set():
                logger.info("Finnhub WS reconnecting in %.0fs...", backoff)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                backoff = min(backoff * 2, max_backoff)
    finally:
        flush_task.cancel()
        indicator_task.cancel()
        validate_task.cancel()
        await asyncio.gather(flush_task, indicator_task, validate_task, return_exceptions=True)
