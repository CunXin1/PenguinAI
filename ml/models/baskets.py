"""Curated ticker baskets for specialized (per-basket, per-horizon) ML models.

A basket is a hand-picked list of tickers that share market dynamics; one model is
trained on the pooled rows of all its members per (timeframe, horizon). Pooling gives
far more data than a single-stock model (which overfits) while still being more
specialized than the global model. Membership may overlap (NVDA is in both nasdaq10
and semis); serve-time resolution picks the most specific basket a ticker belongs to,
falling back to the global model when it is in none.

Roadmap (not built yet): alongside `nasdaq10`, add a small-cap basket and a
whole-market basket so the product can offer large-cap / small-cap / broad views.
"""

from __future__ import annotations

# NASDAQ-listed top 10 by market cap (mega-cap growth; move largely together).
NASDAQ10 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "AVGO",
    "META", "GOOGL", "TSLA", "NFLX", "COST",
]

BASKETS: dict[str, list[str]] = {
    "nasdaq10": NASDAQ10,
    # "smallcap": [...],      # TODO (roadmap)
    # "wholemarket": [...],   # TODO (roadmap)
}


def basket_for(ticker: str) -> str | None:
    """Most-specific basket a ticker belongs to, or None (-> global model fallback).
    Single-membership today; extend with a priority order when baskets overlap."""
    t = ticker.upper()
    for name, members in BASKETS.items():
        if t in members:
            return name
    return None
