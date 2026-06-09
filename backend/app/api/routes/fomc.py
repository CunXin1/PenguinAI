"""
FOMC API — statements, hawk/dove scores, and meeting schedule.

Reads from the ``fomc_statements`` table (populated by the data scraper).
Also provides a static FOMC meeting schedule for the countdown widget.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

FOMC_MEETINGS = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-05-05", "2027-06-16",
    "2027-07-28", "2027-09-22", "2027-10-27", "2027-12-15",
]

_cache: dict[str, tuple[float, object]] = {}
_STATEMENTS_TTL = 3600.0


def _get_cached(key: str, ttl: float):
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > ttl:
        del _cache[key]
        return None
    return data


def _set_cache(key: str, data: object) -> None:
    _cache[key] = (time.monotonic(), data)


def _map_statement(row) -> dict:
    ts = row.get("time")
    unix_ts = 0
    date_str = ""
    if ts is not None:
        try:
            if isinstance(ts, datetime):
                unix_ts = int(ts.timestamp())
                date_str = ts.strftime("%Y-%m-%d")
            else:
                dt = datetime.fromisoformat(str(ts))
                unix_ts = int(dt.timestamp())
                date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    score = row.get("hawk_dove_score")
    return {
        "date": date_str,
        "datetime": unix_ts,
        "hawk_dove_score": float(score) if score is not None else None,
        "summary": row.get("summary"),
        "document_url": row.get("document_url"),
    }


@router.get("/statements")
async def get_fomc_statements(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
):
    """All FOMC statements with hawk/dove scores, most recent first."""
    cache_key = f"fomc:statements:{limit}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    rows = await db.execute(
        text(
            "SELECT time, document_url, hawk_dove_score, summary "
            "FROM fomc_statements "
            "ORDER BY time DESC "
            "LIMIT :limit"
        ),
        {"limit": limit},
    )
    result = [_map_statement(r) for r in rows.mappings()]
    _set_cache(cache_key, result)
    return result


@router.get("/trend")
async def get_fomc_trend(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=50),
):
    """Hawk/dove score time-series for chart visualization (oldest first)."""
    cache_key = f"fomc:trend:{limit}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    rows = await db.execute(
        text(
            "SELECT time, hawk_dove_score "
            "FROM fomc_statements "
            "WHERE hawk_dove_score IS NOT NULL "
            "ORDER BY time DESC "
            "LIMIT :limit"
        ),
        {"limit": limit},
    )
    points = []
    for r in rows.mappings():
        ts = r["time"]
        score = r["hawk_dove_score"]
        date_str = ""
        if isinstance(ts, datetime):
            date_str = ts.strftime("%Y-%m-%d")
        elif ts is not None:
            try:
                date_str = datetime.fromisoformat(str(ts)).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        points.append({"date": date_str, "score": float(score)})

    points.reverse()
    _set_cache(cache_key, points)
    return points


@router.get("/next-meeting")
async def get_next_meeting():
    """Next scheduled FOMC meeting date and countdown."""
    now = datetime.now(UTC)
    today_str = now.strftime("%Y-%m-%d")

    next_date = None
    for d in FOMC_MEETINGS:
        if d >= today_str:
            next_date = d
            break

    if next_date is None:
        return {"next_meeting": None, "days_until": None}

    meeting_dt = datetime.strptime(next_date, "%Y-%m-%d").replace(tzinfo=UTC)
    delta = meeting_dt - now
    days_until = max(0, delta.days)

    return {
        "next_meeting": next_date,
        "days_until": days_until,
    }


@router.get("/schedule")
async def get_fomc_schedule():
    """Full FOMC meeting schedule (for calendar display)."""
    now_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return [
        {"date": d, "past": d < now_str}
        for d in FOMC_MEETINGS
    ]
