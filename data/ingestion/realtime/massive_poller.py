"""Massive 1-min poller — keeps market_data_1min fresh for the symbols the IBKR
stream does NOT cover (the rest of the watched 1-min universe), then recomputes
indicators. ~15-min delayed (Starter plan), no TWS needed.

Also acts as HOT STANDBY for IBKR symbols: if any IBKR-covered ticker's latest
bar is older than _IBKR_STALE_THRESHOLD, Massive polls it as a fallback so core
symbols (SPY, NVDA, etc.) are never dark for more than ~2 minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from data.ingestion.realtime.indicators import update_indicators

logger = logging.getLogger("realtime.massive")
ET = ZoneInfo("America/New_York")

_LAST_SQL = text("SELECT max(time) FROM market_data_1min WHERE ticker = :t")
_STALE_SQL = text(
    "SELECT ticker FROM market_data_1min"
    " WHERE ticker = ANY(:syms)"
    " GROUP BY ticker"
    " HAVING max(time) < now() - :threshold"
)
_IBKR_STALE_THRESHOLD = timedelta(minutes=2)
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

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


async def poll_symbol(engine, client: httpx.AsyncClient, base: str, key: str, sym: str) -> int:
    """Fetch today's new 1-min bars for `sym`, upsert, recompute indicators.

    Returns:
        positive int = bars written
        0  = no new data (normal)
        -1 = retryable error (rate-limited or server error)
    """
    async with engine.connect() as conn:
        last = (await conn.execute(_LAST_SQL, {"t": sym})).scalar()
    last_ms = int(last.timestamp() * 1000) if last else 0
    today = datetime.now(ET).date()
    frm = (today - timedelta(days=4)).isoformat()
    url = (
        f"{base}/v2/aggs/ticker/{sym}/range/1/minute/{frm}/{today.isoformat()}"
        f"?adjusted=false&sort=asc&limit=50000&apiKey={key}"
    )
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("massive %s http error: %r", sym, exc)
        return -1
    if resp.status_code in _RETRYABLE_STATUSES:
        logger.warning("massive %s: HTTP %d (retryable)", sym, resp.status_code)
        return -1
    if resp.status_code != 200:
        logger.debug("massive %s: HTTP %d (non-retryable, skipping)", sym, resp.status_code)
        return 0
    try:
        results = (resp.json() or {}).get("results") or []
    except Exception:  # noqa: BLE001
        logger.warning("massive %s: malformed JSON response", sym)
        return -1

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


async def run(
    engine,
    settings,
    stop: asyncio.Event,
    symbols: list[str],
    ibkr_fallback_symbols: list[str] | None = None,
) -> None:
    """Poll Massive for `symbols` every interval. If `ibkr_fallback_symbols` is
    provided, also check those tickers each cycle and poll any whose latest bar
    is older than _IBKR_STALE_THRESHOLD — hot standby for IBKR outages."""
    if not settings.MASSIVE_API_KEY:
        logger.warning("MASSIVE_API_KEY empty — Massive poller disabled")
        return
    if not symbols and not ibkr_fallback_symbols:
        logger.info("Massive poller: no symbols to poll")
        return
    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    sem = asyncio.Semaphore(8)
    interval = settings.MASSIVE_POLL_INTERVAL
    ibkr_fb = ibkr_fallback_symbols or []
    logger.info(
        "Massive poller: %d symbols every %ds + %d IBKR fallback",
        len(symbols), interval, len(ibkr_fb),
    )

    consecutive_failures: dict[str, int] = {}

    async def one(client: httpx.AsyncClient, sym: str, jitter: float) -> int:
        await asyncio.sleep(jitter)
        async with sem:
            try:
                result = await poll_symbol(engine, client, base, key, sym)
            except Exception as exc:  # noqa: BLE001
                logger.error("poll %s: %r", sym, exc)
                result = -1

            if result < 0:
                consecutive_failures[sym] = consecutive_failures.get(sym, 0) + 1
                n = consecutive_failures[sym]
                if n == 5:
                    logger.warning("massive %s: 5 consecutive failures", sym)
                elif n == 20:
                    logger.error("massive %s: 20 consecutive failures — possible permanent issue", sym)
                return 0
            consecutive_failures.pop(sym, None)
            return result

    async def _stale_ibkr_tickers() -> list[str]:
        """Return IBKR-assigned tickers whose latest bar is older than the threshold."""
        if not ibkr_fb:
            return []
        async with engine.connect() as conn:
            rows = (
                await conn.execute(_STALE_SQL, {"syms": ibkr_fb, "threshold": _IBKR_STALE_THRESHOLD})
            ).scalars().all()
        return list(rows)

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        while not stop.is_set():
            stale = await _stale_ibkr_tickers()
            if stale:
                logger.warning("IBKR fallback: %d stale tickers → Massive: %s", len(stale), stale[:10])
            batch = symbols + stale
            if not batch:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                continue
            jitters = [random.uniform(0, interval * 0.3) for _ in batch]
            res = await asyncio.gather(*(one(client, s, j) for s, j in zip(batch, jitters, strict=False)))
            total = sum(res)
            if total:
                fb_total = sum(res[len(symbols):])
                msg = f"massive poll: +{total} bars across {sum(1 for x in res if x)} symbols"
                if fb_total:
                    msg += f" (incl. {fb_total} IBKR-fallback bars)"
                logger.info(msg)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
