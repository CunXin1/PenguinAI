"""
IBKR real-time 1-minute bar stream via ib_insync.
Subscribes to real-time bars during market hours, writes to TimescaleDB.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ib_insync import IB, BarData, Contract, Stock, util

logger = logging.getLogger(__name__)


class IBKRStream:
    def __init__(self, host: str, port: int, client_id: int):
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib = IB()
        self._subscriptions: dict[str, object] = {}

    async def connect(self) -> None:
        await self._ib.connectAsync(self.host, self.port, clientId=self.client_id)
        logger.info("Connected to IBKR at %s:%d", self.host, self.port)

    async def disconnect(self) -> None:
        self._ib.disconnect()
        logger.info("Disconnected from IBKR")

    async def subscribe_tickers(self, tickers: list[str], on_bar_callback) -> None:
        """Subscribe to real-time 5-second bars (aggregated to 1-min in callback)."""
        for ticker in tickers:
            contract = Stock(ticker, "SMART", "USD")
            bars = self._ib.reqRealTimeBars(
                contract,
                barSize=5,               # 5-second bars (smallest available)
                whatToShow="TRADES",
                useRTH=True,
            )
            bars.updateEvent += lambda bar_list, ticker=ticker: on_bar_callback(ticker, bar_list)
            self._subscriptions[ticker] = bars
            logger.debug("Subscribed to real-time bars: %s", ticker)

    async def fetch_historical_1min(
        self,
        ticker: str,
        duration: str = "1 D",
    ) -> list[dict]:
        """Pull historical 1-min bars for a single ticker (up to IBKR limits)."""
        contract = Stock(ticker, "SMART", "USD")
        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        return [self._bar_to_dict(ticker, bar) for bar in bars]

    def _bar_to_dict(self, ticker: str, bar: BarData) -> dict:
        return {
            "time": bar.date if isinstance(bar.date, datetime) else datetime.fromisoformat(str(bar.date)).replace(tzinfo=timezone.utc),
            "ticker": ticker,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": int(bar.volume),
            "vwap": getattr(bar, "average", None),
            "source": "ibkr",
        }

    async def run_forever(self, tickers: list[str], db_writer) -> None:
        """Main loop: connect, subscribe, stream bars to DB."""
        await self.connect()

        aggregator = MinuteBarAggregator(db_writer)
        await self.subscribe_tickers(tickers, aggregator.on_5sec_bar)

        logger.info("IBKR stream running for %d tickers", len(tickers))
        try:
            while True:
                await asyncio.sleep(60)
                await aggregator.flush_complete_minutes()
        except asyncio.CancelledError:
            await self.disconnect()


class MinuteBarAggregator:
    """Aggregates 5-second IBKR bars into complete 1-minute bars."""

    def __init__(self, db_writer):
        self._db_writer = db_writer
        self._buffers: dict[str, list] = {}

    def on_5sec_bar(self, ticker: str, bar_list) -> None:
        if not bar_list:
            return
        bar = bar_list[-1]
        minute = bar.time.replace(second=0, microsecond=0)
        key = (ticker, minute)
        self._buffers.setdefault(key, []).append(bar)

    async def flush_complete_minutes(self) -> None:
        from datetime import datetime, timezone
        now_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        complete = {k: v for k, v in self._buffers.items() if k[1] < now_minute}
        for (ticker, minute), bars in complete.items():
            row = {
                "time": minute,
                "ticker": ticker,
                "open": bars[0].open,
                "high": max(b.high for b in bars),
                "low": min(b.low for b in bars),
                "close": bars[-1].close,
                "volume": sum(b.volume for b in bars),
                "vwap": None,
                "source": "ibkr",
            }
            await self._db_writer(row)
            del self._buffers[(ticker, minute)]
