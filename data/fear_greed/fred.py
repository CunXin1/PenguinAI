"""FRED VIX (VIXCLS) — backup source for the VIX series.

Uses the official FRED API (key already configured as ``FRED_API_KEY``). FRED
has no VVIX series, so this covers VIX only and returns close-only rows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


async def fetch_fred_vix(
    api_key: str, *, start: str = "1990-01-01", timeout: float = 30.0
) -> list[dict]:
    """Return VIX close rows from FRED VIXCLS. Empty if no key or on failure."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                FRED_BASE,
                params={
                    "series_id": "VIXCLS",
                    "api_key": api_key,
                    "file_type": "json",
                    "observation_start": start,
                    "sort_order": "asc",
                },
            )
            if resp.status_code != 200:
                logger.warning("FRED VIXCLS returned HTTP %d", resp.status_code)
                return []
            data = resp.json()
    except Exception:
        logger.warning("FRED VIXCLS fetch failed", exc_info=True)
        return []

    rows: list[dict] = []
    for obs in data.get("observations", []):
        val = obs.get("value", ".")
        if val == ".":
            continue
        try:
            close = float(val)
            day = datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=UTC)
        except (ValueError, KeyError):
            continue
        rows.append(
            {
                "time": day,
                "symbol": "VIX",
                "open": None,
                "high": None,
                "low": None,
                "close": close,
            }
        )
    return rows
