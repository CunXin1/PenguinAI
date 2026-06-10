"""CNN Fear & Greed Index fetcher (free JSON, no API key).

CNN's dataviz endpoint bot-blocks (HTTP 418, "I'm a teapot. You're a bot.")
unless the request carries a full set of browser headers — notably an
``Origin``/``Referer`` of cnn.com plus the ``sec-ch-ua`` client hints. We
replicate exactly the header set that the cnn.com front-end sends.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# Required to get past CNN's 418 bot filter — verified empirically.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.cnn.com",
    "Referer": "https://www.cnn.com/",
    "sec-ch-ua": '"Chromium";v="123", "Not:A-Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# The seven indicators CNN surfaces on its site (sp125 / vix_50 are alternates
# we deliberately skip — they duplicate momentum / volatility).
COMPONENT_KEYS = [
    "market_momentum_sp500",
    "stock_price_strength",
    "stock_price_breadth",
    "put_call_options",
    "market_volatility_vix",
    "junk_bond_demand",
    "safe_haven_demand",
]

COMPONENT_LABELS = {
    "market_momentum_sp500": "Market Momentum",
    "stock_price_strength": "Stock Price Strength",
    "stock_price_breadth": "Stock Price Breadth",
    "put_call_options": "Put/Call Options",
    "market_volatility_vix": "Market Volatility",
    "junk_bond_demand": "Junk Bond Demand",
    "safe_haven_demand": "Safe Haven Demand",
}


def _f(v: object) -> float | None:
    try:
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def fetch_fear_greed(
    url: str = CNN_URL, timeout: float = 20.0, start_date: str | None = None
) -> dict | None:
    """Fetch + parse the CNN Fear & Greed payload.

    ``start_date`` (``YYYY-MM-DD``) is appended to the graphdata path to pull the
    full history back to that day: CNN serves multi-year history this way, whereas
    the bare endpoint returns only ~1 year. CNN data exists from ~2020-09-01.

    Returns a dict::

        {
          "score": float, "rating": str, "timestamp": str,
          "previous_close" / "previous_1_week" / "previous_1_month"
            / "previous_1_year": float | None,
          "components": {key: {"score", "rating", "label"}},   # latest snapshot
          "history": [(datetime, score, rating), ...],          # daily, ascending
        }

    Returns ``None`` on any network / parse failure.
    """
    try:
        target = f"{url.rstrip('/')}/{start_date}" if start_date else url
        async with httpx.AsyncClient(timeout=timeout, headers=_HEADERS) as client:
            resp = await client.get(target)
            if resp.status_code != 200:
                logger.warning("CNN fear&greed returned HTTP %d", resp.status_code)
                return None
            raw = resp.json()
    except Exception:
        logger.warning("CNN fear&greed fetch failed", exc_info=True)
        return None

    fg = raw.get("fear_and_greed") or {}
    if "score" not in fg:
        logger.warning("CNN fear&greed payload missing 'score'")
        return None

    history: list[tuple[datetime, float, str]] = []
    for p in (raw.get("fear_and_greed_historical") or {}).get("data") or []:
        x, y = p.get("x"), p.get("y")
        if x is None or y is None:
            continue
        history.append(
            (datetime.fromtimestamp(x / 1000, tz=UTC), float(y), p.get("rating", ""))
        )
    history.sort(key=lambda t: t[0])

    components: dict[str, dict] = {}
    for key in COMPONENT_KEYS:
        c = raw.get(key)
        if not c:
            continue
        components[key] = {
            "key": key,
            "label": COMPONENT_LABELS[key],
            "score": _f(c.get("score")),
            "rating": c.get("rating"),
        }

    return {
        "score": float(fg["score"]),
        "rating": fg.get("rating", ""),
        "timestamp": fg.get("timestamp"),
        "previous_close": _f(fg.get("previous_close")),
        "previous_1_week": _f(fg.get("previous_1_week")),
        "previous_1_month": _f(fg.get("previous_1_month")),
        "previous_1_year": _f(fg.get("previous_1_year")),
        "components": components,
        "history": history,
    }
