"""On-demand warm-up: when a user opens a ticker we don't stream, pull its recent
1-min bars from Massive into market_data_1min and compute indicators, so the
chart fills immediately. (IBKR on-demand isn't practical per-request — it needs
the streaming process + TWS; the supervisor's IBKR stream covers the watchlist,
Massive covers everything else.)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from data.ingestion.realtime.config import RealtimeSettings
from data.ingestion.realtime.indicators import update_indicators
from data.ingestion.realtime.massive_poller import _UPSERT_SQL

logger = logging.getLogger("realtime.ondemand")
ET = ZoneInfo("America/New_York")
_PAGE = 50_000

_HAS_SQL = text("SELECT count(*) FROM market_data_1min WHERE ticker = :t")

_warm_locks: dict[str, asyncio.Lock] = {}
_warm_locks_guard = asyncio.Lock()


async def _get_ticker_lock(ticker: str) -> asyncio.Lock:
    async with _warm_locks_guard:
        if ticker not in _warm_locks:
            _warm_locks[ticker] = asyncio.Lock()
        return _warm_locks[ticker]


def _with_key(url: str, key: str) -> str:
    if not key or "apiKey=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}apiKey={key}"


async def warm_ticker(engine, ticker: str, *, days: int = 5, settings: RealtimeSettings | None = None) -> int:
    """Fetch ~`days` of recent 1-min bars for `ticker` from Massive, upsert into
    market_data_1min, compute indicators. Returns bars written (0 if no key / no data).

    Concurrent calls for the same ticker are serialised: the second caller waits for
    the first to finish, then returns 0 (data is already warm).
    """
    s = settings or RealtimeSettings()
    ticker = ticker.upper()
    if not s.MASSIVE_API_KEY:
        return 0

    lock = await _get_ticker_lock(ticker)
    if not lock.acquire_nowait():
        async with lock:
            return 0

    try:
        return await _warm_ticker_inner(engine, ticker, days=days, settings=s)
    finally:
        lock.release()


async def _warm_ticker_inner(engine, ticker: str, *, days: int, settings: RealtimeSettings) -> int:
    to = datetime.now(ET).date()
    frm = to - timedelta(days=days)
    base = settings.MASSIVE_BASE_URL.rstrip("/")
    url: str | None = _with_key(
        f"{base}/v2/aggs/ticker/{ticker}/range/1/minute/{frm.isoformat()}/{to.isoformat()}"
        f"?adjusted=false&sort=asc&limit={_PAGE}",
        settings.MASSIVE_API_KEY,
    )
    written = 0
    async with httpx.AsyncClient(
        timeout=40.0, headers={"Authorization": f"Bearer {settings.MASSIVE_API_KEY}"}
    ) as client:
        while url:
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                logger.warning("warm %s: %r", ticker, exc)
                break
            if resp.status_code != 200:
                logger.warning("warm %s: HTTP %d", ticker, resp.status_code)
                break
            data = resp.json() or {}
            rows = []
            for b in data.get("results") or []:
                t = b.get("t")
                o, h, low, c = b.get("o"), b.get("h"), b.get("l"), b.get("c")
                if t is None or None in (o, h, low, c):
                    continue
                rows.append(
                    {
                        "time": datetime.fromtimestamp(t / 1000.0, tz=UTC), "ticker": ticker,
                        "open": o, "high": h, "low": low, "close": c,
                        "volume": int(round(float(b.get("v") or 0))), "vwap": b.get("vw"),
                    }
                )
            if rows:
                async with engine.begin() as conn:
                    await conn.execute(_UPSERT_SQL, rows)
                written += len(rows)
            nxt = data.get("next_url")
            url = _with_key(nxt, settings.MASSIVE_API_KEY) if nxt else None
    if written:
        await update_indicators(engine, ticker, full=True)
        logger.info("warmed %s: %d 1-min bars", ticker, written)
    return written
