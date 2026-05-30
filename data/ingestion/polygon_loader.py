"""
Polygon.io historical data loader.
Pulls minute/30-min/daily bars in bulk and writes to TimescaleDB.
Handles paging and rate limiting automatically.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

POLYGON_BASE = "https://api.polygon.io/v2"


class PolygonLoader:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=POLYGON_BASE,
            params={"apiKey": api_key},
            timeout=30,
        )

    async def fetch_aggregates(
        self,
        ticker: str,
        multiplier: int,
        timespan: str,        # 'minute' | 'hour' | 'day'
        from_date: date,
        to_date: date,
        adjusted: bool = True,
    ) -> list[dict]:
        """
        Fetch all bars for a ticker in a date range, auto-paging.
        Returns list of bar dicts.
        """
        url = f"/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        params = {
            "adjusted": str(adjusted).lower(),
            "sort": "asc",
            "limit": 50000,
        }
        bars = []

        while url:
            resp = await self._client.get(url, params=params)
            if resp.status_code == 429:  # rate limit
                await asyncio.sleep(12)
                continue
            resp.raise_for_status()
            data = resp.json()

            for result in data.get("results", []):
                bars.append({
                    "ticker": ticker,
                    "time": _ts_to_dt(result["t"]),
                    "open": result["o"],
                    "high": result["h"],
                    "low": result["l"],
                    "close": result["c"],
                    "volume": int(result["v"]),
                    "vwap": result.get("vw"),
                    "adjusted": adjusted,
                    "source": "polygon",
                })

            url = data.get("next_url")  # Polygon paginates via next_url
            if url:
                params = {}             # next_url includes all params
                await asyncio.sleep(0.2)

        return bars

    async def bulk_load_tickers(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "minute",
        multiplier: int = 30,
        db_writer=None,
    ) -> None:
        """Batch download for many tickers, calling db_writer for each chunk."""
        logger.info("Starting Polygon bulk load: %d tickers, %s/%s to %s", len(tickers), multiplier, timespan, to_date)

        for i, ticker in enumerate(tickers):
            try:
                bars = await self.fetch_aggregates(ticker, multiplier, timespan, from_date, to_date)
                if bars and db_writer:
                    await db_writer(bars)
                logger.info("[%d/%d] %s: %d bars loaded", i + 1, len(tickers), ticker, len(bars))
            except Exception as e:
                logger.error("Failed to load %s: %s", ticker, e)

            await asyncio.sleep(0.1)   # polite pacing

    async def close(self) -> None:
        await self._client.aclose()


def _ts_to_dt(ts_ms: int):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
