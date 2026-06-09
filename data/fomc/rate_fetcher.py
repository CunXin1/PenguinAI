"""Federal funds rate fetcher — pulls target rate from FRED API.

Uses the FRED series DFEDTARU (upper target) and DFEDTARL (lower target),
which only exist from 2008-12-16 onward (the start of the target-range era).

Refresh policy (see ``refresh_rates``): the hardcoded table is always seeded
first as a full-range baseline, then FRED is overlaid on top so that recent
values are official while the pre-2008 single-target history is preserved.

Schedule (managed by scheduler.py):
  - Post-FOMC: 1h, 1d, 3d after each meeting (catch rate changes fast)
  - Weekly: every Friday (keep data fresh)
  - Startup: once
"""

import asyncio
import logging

import httpx
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("fomc.rate_fetcher")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
SERIES_UPPER = "DFEDTARU"
SERIES_LOWER = "DFEDTARL"

_UPSERT_SQL = sa_text("""
    INSERT INTO fomc_fed_funds_rate (date, rate_low, rate_high, source)
    VALUES (:date, :rate_low, :rate_high, :source)
    ON CONFLICT (date) DO UPDATE SET
        rate_low  = EXCLUDED.rate_low,
        rate_high = EXCLUDED.rate_high,
        source    = EXCLUDED.source
""")


async def _fetch_fred_series(
    client: httpx.AsyncClient, series_id: str, api_key: str, start: str
) -> dict[str, float]:
    """Fetch a FRED series and return {date_str: value} dict."""
    resp = await client.get(
        FRED_BASE,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "asc",
        },
    )
    if resp.status_code != 200:
        logger.warning("FRED %s returned %d", series_id, resp.status_code)
        return {}

    data = resp.json()
    result = {}
    for obs in data.get("observations", []):
        val = obs.get("value", ".")
        if val == ".":
            continue
        try:
            result[obs["date"]] = float(val)
        except (ValueError, KeyError):
            continue
    return result


async def fetch_rates_from_fred(
    db_url: str, api_key: str, start_date: str = "2000-01-01"
) -> int:
    """Fetch upper+lower target rates from FRED and upsert into DB.

    Returns the number of rows upserted.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        upper = await _fetch_fred_series(client, SERIES_UPPER, api_key, start_date)
        lower = await _fetch_fred_series(client, SERIES_LOWER, api_key, start_date)

    if not upper and not lower:
        logger.warning("FRED returned no data for either series")
        return 0

    all_dates = sorted(set(upper.keys()) | set(lower.keys()))

    engine = create_async_engine(db_url)
    count = 0
    try:
        async with engine.begin() as conn:
            for d in all_dates:
                hi = upper.get(d)
                lo = lower.get(d)
                if hi is None and lo is None:
                    continue
                if hi is None:
                    hi = lo
                if lo is None:
                    lo = hi
                await conn.execute(_UPSERT_SQL, {
                    "date": d,
                    "rate_low": lo,
                    "rate_high": hi,
                    "source": "FRED",
                })
                count += 1
        logger.info("fed funds rate: upserted %d rows from FRED", count)
    finally:
        await engine.dispose()
    return count


async def seed_from_hardcoded(db_url: str) -> int:
    """Seed the DB table from the hardcoded rate history (bootstrap/fallback)."""
    from data.fomc.fed_funds_rate import FED_FUNDS_RATE_HISTORY

    engine = create_async_engine(db_url)
    count = 0
    try:
        async with engine.begin() as conn:
            for date_str, (lo, hi) in sorted(FED_FUNDS_RATE_HISTORY.items()):
                await conn.execute(_UPSERT_SQL, {
                    "date": date_str,
                    "rate_low": lo,
                    "rate_high": hi,
                    "source": "hardcoded",
                })
                count += 1
        logger.info("fed funds rate: seeded %d rows from hardcoded table", count)
    finally:
        await engine.dispose()
    return count


async def refresh_rates(db_url: str, fred_api_key: str) -> int:
    """Refresh rates: hardcoded baseline first, then FRED overlaid on top.

    Strategy (hardcoded as floor, FRED takes priority where available):

    1. Always seed the hardcoded table first — it covers the full 2000-present
       history including the pre-2008 single-target era.
    2. Then overlay FRED. Its DFEDTARU/DFEDTARL series only start 2008-12-16, so
       FRED's ``ON CONFLICT DO UPDATE`` refreshes everything from then on with the
       official daily values, while the pre-2008 rows stay sourced from hardcoded.

    This guarantees full-range history regardless of whether FRED is reachable,
    while keeping recent data authoritative when an API key is configured.
    """
    seeded = await seed_from_hardcoded(db_url)

    if not fred_api_key:
        return seeded

    try:
        fred_count = await fetch_rates_from_fred(db_url, fred_api_key)
        if fred_count > 0:
            return fred_count
    except Exception:
        logger.warning("FRED fetch failed, hardcoded baseline retained", exc_info=True)

    return seeded


if __name__ == "__main__":
    import os

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai",
    )
    fred_key = os.getenv("FRED_API_KEY", "")
    count = asyncio.run(refresh_rates(db_url, fred_key))
    print(f"Done — {count} rate entries upserted.")
