"""Fear & Greed Index + VIX/VVIX volatility API.

Reads the ``fear_greed_index`` and ``volatility_index`` tables populated by the
``data.fear_greed`` scheduler (CNN + CBOE/Yahoo/FRED, multi-source). All
endpoints are public and backed by a short in-process TTL cache.
"""

from __future__ import annotations

import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db

router = APIRouter()

# ── In-process TTL cache (same pattern as the FOMC route) ─────────────────────
_cache: dict[str, tuple[float, object]] = {}
_TTL = 300.0  # 5 min — the scheduler refreshes hourly


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > _TTL:
        del _cache[key]
        return None
    return data


def _set_cache(key: str, data: object) -> None:
    _cache[key] = (time.monotonic(), data)


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _label(score: float) -> str:
    if score < 25:
        return "Extreme Fear"
    if score < 45:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 75:
        return "Greed"
    return "Extreme Greed"


_COMPONENT_ORDER = [
    "market_momentum_sp500",
    "stock_price_strength",
    "stock_price_breadth",
    "put_call_options",
    "market_volatility_vix",
    "junk_bond_demand",
    "safe_haven_demand",
]


@router.get("")
async def get_fear_greed(db: Annotated[AsyncSession, Depends(get_db)]):
    """Current index reading: score, rating, the 7 components, and the index value
    at previous close / 1 week / 1 month / 1 year ago (for the comparison strip)."""
    cached = _get_cached("fng:current")
    if cached is not None:
        return cached

    row = (
        await db.execute(
            text(
                "SELECT time, score, rating, components, source "
                "FROM fear_greed_index ORDER BY time DESC LIMIT 1"
            )
        )
    ).mappings().first()
    if row is None:
        result = {"score": None, "rating": None, "label": None,
                  "updated_at": None, "source": None, "previous": {}, "components": []}
        _set_cache("fng:current", result)
        return result

    prev = (
        await db.execute(
            text(
                """
                SELECT
                  (SELECT score FROM fear_greed_index WHERE time < :t
                     ORDER BY time DESC LIMIT 1) AS close,
                  (SELECT score FROM fear_greed_index WHERE time <= :t - INTERVAL '7 days'
                     ORDER BY time DESC LIMIT 1) AS week,
                  (SELECT score FROM fear_greed_index WHERE time <= :t - INTERVAL '1 month'
                     ORDER BY time DESC LIMIT 1) AS month,
                  (SELECT score FROM fear_greed_index WHERE time <= :t - INTERVAL '1 year'
                     ORDER BY time DESC LIMIT 1) AS year
                """
            ),
            {"t": row["time"]},
        )
    ).mappings().first()

    comp_raw = row["components"]
    if isinstance(comp_raw, str):
        try:
            comp_raw = json.loads(comp_raw)
        except (ValueError, TypeError):
            comp_raw = {}
    comp_raw = comp_raw or {}
    components = [comp_raw[k] for k in _COMPONENT_ORDER if k in comp_raw]

    score = float(row["score"])
    result = {
        "score": round(score, 2),
        "rating": row["rating"],
        "label": _label(score),
        "updated_at": row["time"].isoformat(),
        "source": row["source"],
        "previous": {
            "close": _f(prev["close"]) if prev else None,
            "week": _f(prev["week"]) if prev else None,
            "month": _f(prev["month"]) if prev else None,
            "year": _f(prev["year"]) if prev else None,
        },
        "components": components,
    }
    _set_cache("fng:current", result)
    return result


@router.get("/history")
async def get_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(default=365, ge=7, le=3650),
):
    """Daily Fear & Greed score series for the history chart (ascending)."""
    key = f"fng:history:{days}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    rows = await db.execute(
        text(
            "SELECT time, score, rating FROM fear_greed_index "
            "WHERE time >= now() - make_interval(days => :days) ORDER BY time ASC"
        ),
        {"days": days},
    )
    result = [
        {"date": r["time"].date().isoformat(), "score": float(r["score"]), "rating": r["rating"]}
        for r in rows.mappings()
    ]
    _set_cache(key, result)
    return result


@router.get("/volatility")
async def get_volatility(
    db: Annotated[AsyncSession, Depends(get_db)],
    symbol: str = Query(default="VIX"),
    days: int = Query(default=365, ge=7, le=20000),
):
    """Daily OHLC series for a volatility index (VIX or VVIX), ascending."""
    symbol = symbol.upper()
    if symbol not in ("VIX", "VVIX"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="symbol must be VIX or VVIX",
        )
    key = f"vol:{symbol}:{days}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    rows = await db.execute(
        text(
            "SELECT time, open, high, low, close FROM volatility_index "
            "WHERE symbol = :sym AND time >= now() - make_interval(days => :days) "
            "ORDER BY time ASC"
        ),
        {"sym": symbol, "days": days},
    )
    bars = [
        {
            "time": int(r["time"].timestamp()),
            "date": r["time"].date().isoformat(),
            "open": _f(r["open"]),
            "high": _f(r["high"]),
            "low": _f(r["low"]),
            "close": _f(r["close"]),
        }
        for r in rows.mappings()
    ]
    latest = bars[-1]["close"] if bars else None
    prev = bars[-2]["close"] if len(bars) >= 2 else None
    change_pct = (
        round((latest - prev) / prev * 100, 2) if latest and prev else None
    )
    result = {"symbol": symbol, "latest": latest, "change_pct": change_pct, "bars": bars}
    _set_cache(key, result)
    return result
