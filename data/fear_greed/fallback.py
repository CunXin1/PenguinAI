"""Computed Fear & Greed fallback — used only when CNN is unreachable.

VIX is the market's canonical "fear gauge", so a serviceable proxy is the
inverted trailing percentile of VIX: when VIX is low relative to the past year
the market is calm (greed); when it spikes, fear. This keeps the page populated
during a CNN outage. Rows are stored with ``source='computed'`` so the UI can
label them as an estimate rather than the official index.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_WINDOW = 252  # ~1 trading year


def rating_for(score: float) -> str:
    if score < 25:
        return "extreme fear"
    if score < 45:
        return "fear"
    if score <= 55:
        return "neutral"
    if score <= 75:
        return "greed"
    return "extreme greed"


def compute_fng_from_vix(vix_rows: list[dict]) -> dict | None:
    """Build a CNN-shaped payload from VIX rows. Returns None if too little data."""
    pts = sorted(
        ((r["time"], r["close"]) for r in vix_rows if r.get("close") is not None),
        key=lambda t: t[0],
    )
    if len(pts) < 30:
        return None

    closes = [c for _, c in pts]
    history: list[tuple[datetime, float, str]] = []
    for i, (t, _) in enumerate(pts):
        window = closes[max(0, i - _WINDOW + 1) : i + 1]
        cur = closes[i]
        # percentile rank of the current VIX within the trailing window
        rank = sum(1 for v in window if v <= cur) / len(window)
        score = round(100.0 * (1.0 - rank), 2)  # high VIX → low score (fear)
        history.append((t, score, rating_for(score)))

    cur_score = history[-1][1]
    return {
        "score": cur_score,
        "rating": rating_for(cur_score),
        "timestamp": pts[-1][0].isoformat(),
        "previous_close": None,
        "previous_1_week": None,
        "previous_1_month": None,
        "previous_1_year": None,
        "components": {
            "market_volatility_vix": {
                "key": "market_volatility_vix",
                "label": "Market Volatility (VIX proxy)",
                "score": cur_score,
                "rating": rating_for(cur_score),
            }
        },
        "history": history,
        "source": "computed",
    }
