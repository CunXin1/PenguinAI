"""Massive 1-min poller — keeps market_data_1min fresh for the symbols the IBKR
stream does NOT cover (the rest of the watched 1-min universe), then recomputes
indicators. ~15-min delayed (Starter plan), no TWS needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from data.ingestion.realtime.indicators import update_indicators

logger = logging.getLogger("realtime.massive")
ET = ZoneInfo("America/New_York")

_LAST_SQL = text("SELECT max(time) FROM market_data_1min WHERE ticker = :t")
_UPSERT_SQL = text(
    """
    INSERT INTO market_data_1min (time, ticker, open, high, low, close, volume, vwap, source)
    VALUES (:time, :ticker, :open, :high, :low, :close, :volume, :vwap, 'massive')
    ON CONFLICT (ticker, time) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
        close = EXCLUDED.close, volume = EXCLUDED.volume, vwap = EXCLUDED.vwap,
        source = 'massive'
    """
)


async def poll_symbol(engine, client: httpx.AsyncClient, base: str, key: str, sym: str) -> int:
    """Fetch today's new 1-min bars for `sym`, upsert, recompute indicators."""
    async with engine.connect() as conn:
        last = (await conn.execute(_LAST_SQL, {"t": sym})).scalar()
    last_ms = int(last.timestamp() * 1000) if last else 0
    # Trailing range, not a single "today": on weekends / holidays / pre-open the
    # current ET day has no data and Massive 403s a single-day query. A few days
    # back always spans the latest trading day; last_ms below skips already-stored.
    today = datetime.now(ET).date()
    frm = (today - timedelta(days=4)).isoformat()
    url = (
        f"{base}/v2/aggs/ticker/{sym}/range/1/minute/{frm}/{today.isoformat()}"
        f"?adjusted=false&sort=asc&limit=50000&apiKey={key}"
    )
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("massive %s: %r", sym, exc)
        return 0
    if resp.status_code != 200:
        return 0
    results = (resp.json() or {}).get("results") or []

    rows: list[dict] = []
    for b in results:
        t = b.get("t")
        o, h, low, c = b.get("o"), b.get("h"), b.get("l"), b.get("c")
        if t is None or t <= last_ms or None in (o, h, low, c):
            continue
        rows.append(
            {
                "time": datetime.fromtimestamp(t / 1000.0, tz=UTC),
                "ticker": sym,
                "open": o, "high": h, "low": low, "close": c,
                "volume": int(round(float(b.get("v") or 0))),
                "vwap": b.get("vw"),
            }
        )
    if not rows:
        return 0
    async with engine.begin() as conn:
        await conn.execute(_UPSERT_SQL, rows)
    await update_indicators(engine, sym, tail=len(rows) + 4)
    return len(rows)


async def run(engine, settings, stop: asyncio.Event, symbols: list[str]) -> None:
    if not settings.MASSIVE_API_KEY:
        logger.warning("MASSIVE_API_KEY empty — Massive poller disabled")
        return
    if not symbols:
        logger.info("Massive poller: no symbols to poll")
        return
    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    sem = asyncio.Semaphore(8)
    logger.info("Massive poller: %d symbols every %ds", len(symbols), settings.MASSIVE_POLL_INTERVAL)

    async def one(client, sym):
        async with sem:
            try:
                return await poll_symbol(engine, client, base, key, sym)
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                logger.error("poll %s: %r", sym, exc)
                return 0

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        while not stop.is_set():
            res = await asyncio.gather(*(one(client, s) for s in symbols))
            total = sum(res)
            if total:
                logger.info("massive poll: +%d bars across %d symbols", total, sum(1 for x in res if x))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.MASSIVE_POLL_INTERVAL)
