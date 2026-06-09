"""Fetch Fear & Greed (CNN, with computed fallback) + multi-source VIX/VVIX
(CBOE → Yahoo → FRED, merged & cross-checked) → upsert into TimescaleDB.

Mirrors the FOMC loader pattern: async SQLAlchemy engine, raw ``text()`` SQL
with ``ON CONFLICT`` upserts, returns the number of rows written.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .cnn import fetch_fear_greed
from .fallback import compute_fng_from_vix
from .volatility import fetch_all_volatility

logger = logging.getLogger(__name__)

_FNG_UPSERT = text(
    """
    INSERT INTO fear_greed_index (time, score, rating, components, source)
    VALUES (:time, :score, :rating, CAST(:components AS JSONB), :source)
    ON CONFLICT (time) DO UPDATE SET
        score      = EXCLUDED.score,
        rating     = EXCLUDED.rating,
        components = COALESCE(EXCLUDED.components, fear_greed_index.components),
        source     = EXCLUDED.source
    """
)

_VOL_UPSERT = text(
    """
    INSERT INTO volatility_index (time, symbol, open, high, low, close, source)
    VALUES (:time, :symbol, :open, :high, :low, :close, :source)
    ON CONFLICT (symbol, time) DO UPDATE SET
        open   = EXCLUDED.open,
        high   = EXCLUDED.high,
        low    = EXCLUDED.low,
        close  = EXCLUDED.close,
        source = EXCLUDED.source
    """
)


def _day(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


async def _upsert_fng(engine, fng: dict) -> int:
    """One row per calendar day; the latest day also carries the live score +
    the component snapshot. ``source`` is 'cnn' or 'computed' (fallback)."""
    source = fng.get("source", "cnn")
    by_day: dict[datetime, dict] = {}
    for d, score, rating in fng["history"]:
        day = _day(d)
        by_day[day] = {
            "time": day, "score": round(score, 2), "rating": rating,
            "components": None, "source": source,
        }

    live_day = _day(datetime.now(UTC))
    latest = max([*by_day.keys(), live_day])
    by_day.setdefault(
        latest,
        {"time": latest, "score": 0.0, "rating": "", "components": None, "source": source},
    )
    by_day[latest]["score"] = round(fng["score"], 2)
    by_day[latest]["rating"] = fng["rating"]
    by_day[latest]["components"] = json.dumps(fng["components"])
    by_day[latest]["source"] = source

    rows = list(by_day.values())
    async with engine.begin() as conn:
        await conn.execute(_FNG_UPSERT, rows)
    return len(rows)


async def _upsert_vol(engine, rows: list[dict]) -> int:
    written = 0
    for i in range(0, len(rows), 2000):
        batch = rows[i : i + 2000]
        for r in batch:
            r.setdefault("source", "cboe")
        async with engine.begin() as conn:
            await conn.execute(_VOL_UPSERT, batch)
        written += len(batch)
    return written


async def run_loader(database_url: str, *, fred_key: str | None = None) -> int:
    """Fetch all sources and upsert. Returns total rows written."""
    if fred_key is None:
        fred_key = os.getenv("FRED_API_KEY", "")
    engine = create_async_engine(database_url)
    written = 0
    try:
        # ── Volatility first (multi-source, merged + cross-checked) ──
        vol = await fetch_all_volatility(fred_key)
        vix_rows = [r for r in vol["rows"] if r["symbol"] == "VIX"]
        if vol["rows"]:
            n = await _upsert_vol(engine, vol["rows"])
            logger.info("volatility: upserted %d VIX/VVIX rows | crosscheck=%s",
                        n, vol["crosscheck"])
            written += n
        else:
            logger.warning("volatility: all sources failed")

        # ── Fear & Greed: CNN primary, computed-from-VIX fallback ──
        fng = await fetch_fear_greed()
        if not fng:
            logger.warning("fear&greed: CNN unavailable — computing VIX proxy fallback")
            fng = compute_fng_from_vix(vix_rows)
        if fng:
            n = await _upsert_fng(engine, fng)
            logger.info("fear&greed: upserted %d daily rows (score=%.1f %s, source=%s)",
                        n, fng["score"], fng["rating"], fng.get("source", "cnn"))
            written += n
        else:
            logger.warning("fear&greed: no data from CNN or VIX fallback")
    finally:
        await engine.dispose()
    return written
