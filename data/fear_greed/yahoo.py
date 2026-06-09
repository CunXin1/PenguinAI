"""Yahoo Finance chart endpoint — VIX / VVIX daily history.

This hits Yahoo's *public chart JSON API* directly over HTTP (not the yfinance
library). Used as a backup source for the CBOE CSVs and to keep today's value
fresh when CBOE lags by a day.

  GET /v8/finance/chart/^VIX?range=10y&interval=1d
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Map our symbol → Yahoo ticker.
_YQ = {"VIX": "^VIX", "VVIX": "^VVIX"}


def _f(v: object) -> float | None:
    try:
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def fetch_yahoo(symbol: str, *, range_: str = "10y", timeout: float = 25.0) -> list[dict]:
    """Return daily rows for one symbol via Yahoo's chart API. Empty on failure."""
    yq = _YQ.get(symbol.upper())
    if yq is None:
        return []
    url = f"{_BASE}/{yq}"
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=_HEADERS) as client:
            resp = await client.get(url, params={"range": range_, "interval": "1d"})
            if resp.status_code != 200:
                logger.warning("Yahoo %s returned HTTP %d", yq, resp.status_code)
                return []
            data = resp.json()
    except Exception:
        logger.warning("Yahoo fetch failed for %s", yq, exc_info=True)
        return []

    try:
        result = data["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        logger.warning("Yahoo %s: unexpected payload shape", yq)
        return []

    opens, highs, lows, closes = (
        q.get("open", []),
        q.get("high", []),
        q.get("low", []),
        q.get("close", []),
    )
    rows: list[dict] = []
    for i, t in enumerate(ts):
        close = _f(closes[i]) if i < len(closes) else None
        if close is None:
            continue
        # Yahoo timestamps are the session start; bucket to the UTC trading day.
        day = datetime.fromtimestamp(t, tz=UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows.append(
            {
                "time": day,
                "symbol": symbol.upper(),
                "open": _f(opens[i]) if i < len(opens) else None,
                "high": _f(highs[i]) if i < len(highs) else None,
                "low": _f(lows[i]) if i < len(lows) else None,
                "close": close,
            }
        )
    return rows
