"""On-demand daily bars for tickers missing from ``bars_1d``.

Only ~50 symbols are bulk-loaded into ``bars_1d``, so the earnings price-reaction
can't be computed for the long tail of reported tickers. This module fetches a
small daily window on demand so the reaction still shows up.

Primary source is Massive's Polygon-compatible aggregates endpoint
(``/v2/aggs/ticker/{T}/range/1/day/{from}/{to}``) — stateless, key-authed, cheap.
Results are cached in-process with a TTL so the hot ``/earnings`` endpoint doesn't
re-hit Massive on every load. (IBKR historical data needs a live Gateway session,
so it's a poor fit for a request-path fallback and is intentionally not used here.)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime

import httpx

from app.core.config import settings

logger = logging.getLogger("app.daily_prices")

# (date, open, close) rows, ascending by date — matches the bars_1d price_map shape.
DailyRows = list[tuple[date, float, float]]

_TTL_SECONDS = 6 * 3600
_REQUEST_TIMEOUT = 8.0

# (ticker, from, to) -> (expires_at_epoch, rows). Empty rows are cached too (a
# negative cache) so we don't re-hit Massive for tickers it doesn't cover.
_cache: dict[tuple[str, str, str], tuple[float, DailyRows]] = {}
# Per-ticker lock so concurrent requests for the same ticker dedupe to one fetch.
_locks: dict[str, asyncio.Lock] = {}


async def fetch_daily_adjusted(ticker: str, date_from: date, date_to: date) -> DailyRows:
    """Adjusted daily (date, open, close) for ``ticker`` over [from, to], or []."""
    if not settings.MASSIVE_API_KEY:
        return []

    key = (ticker, date_from.isoformat(), date_to.isoformat())
    cached = _cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1]

    lock = _locks.setdefault(ticker, asyncio.Lock())
    async with lock:
        # Re-check inside the lock: a sibling request may have just filled it.
        cached = _cache.get(key)
        if cached and cached[0] > time.time():
            return cached[1]
        rows = await _request_daily(ticker, date_from, date_to)
        _cache[key] = (time.time() + _TTL_SECONDS, rows)
        return rows


async def _request_daily(ticker: str, date_from: date, date_to: date) -> DailyRows:
    base = settings.MASSIVE_BASE_URL.rstrip("/")
    url = (
        f"{base}/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{date_from.isoformat()}/{date_to.isoformat()}"
        f"?adjusted=true&sort=asc&limit=50000&apiKey={settings.MASSIVE_API_KEY}"
    )
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("massive daily %s: HTTP %d", ticker, resp.status_code)
            return []
        results = resp.json().get("results") or []
    except (httpx.HTTPError, ValueError):
        logger.warning("massive daily fetch failed for %s", ticker, exc_info=True)
        return []

    out: DailyRows = []
    for r in results:
        t, o, c = r.get("t"), r.get("o"), r.get("c")
        if t is None or o is None or c is None:
            continue
        # Polygon daily timestamps are ET-midnight; UTC .date() recovers the
        # trading day correctly regardless of the exact midnight convention.
        d = datetime.fromtimestamp(t / 1000.0, tz=UTC).date()
        out.append((d, float(o), float(c)))
    return out
