"""
FOMC API — statements, hawk/dove scores, meeting schedule, rate history,
market reactions, and statement diffs.

Reads from the ``fomc_statements`` table (populated by ``data.fomc.loader``).
Rate history from ``data.fomc.fed_funds_rate`` (hardcoded, cross-verified).
Market reactions from ``bars_1d`` (SPY daily bars).
"""

import difflib
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


@router.get("/rate-history")
async def get_rate_history(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Federal funds rate over time — one point per FOMC statement date.

    Uses the authoritative hardcoded rate table (cross-verified against
    FRED, Fed press releases, and Bankrate). Each point shows the
    effective rate on that meeting date, NOT extracted from statement text.
    """
    cache_key = "fomc:rate-history"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    from data.fomc.fed_funds_rate import get_rate_on_date

    rows = await db.execute(
        text("SELECT DISTINCT time::date AS d FROM fomc_statements ORDER BY d")
    )
    points = []
    for row in rows:
        date_str = str(row[0])
        try:
            low, high = get_rate_on_date(date_str)
            points.append({
                "date": date_str,
                "rate_low": low,
                "rate_high": high,
            })
        except ValueError:
            continue

    _set_cache(cache_key, points)
    return points


@router.get("/market-reaction")
async def get_market_reaction(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=30, ge=1, le=100),
):
    """SPY return on each FOMC meeting day (intraday: close/prev_close - 1).

    Only returns dates where both the FOMC statement AND SPY daily bar exist.
    """
    cache_key = f"fomc:market-reaction:{limit}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    rows = await db.execute(
        text("""
            WITH fomc_dates AS (
                SELECT DISTINCT time::date AS fomc_date
                FROM fomc_statements
                ORDER BY fomc_date DESC
                LIMIT :limit
            ),
            spy AS (
                SELECT
                    b.ts::date AS bar_date,
                    b.adj_close AS close
                FROM bars_1d b
                JOIN instruments i ON i.instrument_id = b.instrument_id
                WHERE i.symbol = 'SPY'
            ),
            spy_with_prev AS (
                SELECT
                    bar_date,
                    close,
                    LAG(close) OVER (ORDER BY bar_date) AS prev_close
                FROM spy
            )
            SELECT
                f.fomc_date,
                s.close,
                s.prev_close
            FROM fomc_dates f
            JOIN spy_with_prev s ON s.bar_date = f.fomc_date
            ORDER BY f.fomc_date DESC
        """),
        {"limit": limit},
    )

    from data.fomc.fed_funds_rate import get_rate_on_date

    result = []
    for r in rows.mappings():
        date_str = str(r["fomc_date"])
        close = r["close"]
        prev = r["prev_close"]
        ret = round((close / prev - 1) * 100, 4) if close and prev and prev > 0 else None
        try:
            low, high = get_rate_on_date(date_str)
        except ValueError:
            low, high = None, None
        result.append({
            "date": date_str,
            "spy_return_pct": ret,
            "spy_close": round(float(close), 2) if close else None,
            "rate_low": low,
            "rate_high": high,
        })

    _set_cache(cache_key, result)
    return result


@router.get("/diff")
async def get_statement_diff(
    db: Annotated[AsyncSession, Depends(get_db)],
    date: str = Query(..., description="Date of the statement to diff (YYYY-MM-DD)"),
):
    """Sentence-level diff between a statement and the previous one.

    Returns added, removed, and unchanged sentences so the frontend can
    render a redline view.
    """
    cache_key = f"fomc:diff:{date}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    from datetime import date as date_type

    try:
        target = date_type.fromisoformat(date)
    except ValueError:
        return {"error": "Invalid date format, use YYYY-MM-DD", "date": date}

    rows = await db.execute(
        text("""
            SELECT time::date AS d, raw_text
            FROM fomc_statements
            WHERE time::date <= :target_date
            ORDER BY time DESC
            LIMIT 2
        """),
        {"target_date": target},
    )
    statements = [(str(r[0]), r[1]) for r in rows]

    if len(statements) < 1 or statements[0][1] is None:
        return {"error": "Statement not found", "date": date}

    current_date, current_text = statements[0]
    if len(statements) < 2 or statements[1][1] is None:
        return {
            "current_date": current_date,
            "previous_date": None,
            "diff": [{"type": "added", "text": s} for s in _split_sentences(current_text)],
        }

    previous_date, previous_text = statements[1]

    prev_sentences = _split_sentences(previous_text)
    curr_sentences = _split_sentences(current_text)

    diff_result = []
    matcher = difflib.SequenceMatcher(None, prev_sentences, curr_sentences)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for s in prev_sentences[i1:i2]:
                diff_result.append({"type": "unchanged", "text": s})
        elif tag == "replace":
            for s in prev_sentences[i1:i2]:
                diff_result.append({"type": "removed", "text": s})
            for s in curr_sentences[j1:j2]:
                diff_result.append({"type": "added", "text": s})
        elif tag == "delete":
            for s in prev_sentences[i1:i2]:
                diff_result.append({"type": "removed", "text": s})
        elif tag == "insert":
            for s in curr_sentences[j1:j2]:
                diff_result.append({"type": "added", "text": s})

    result = {
        "current_date": current_date,
        "previous_date": previous_date,
        "diff": diff_result,
    }
    _set_cache(cache_key, result)
    return result


def _split_sentences(text: str) -> list[str]:
    """Split statement text into sentences, preserving meaningful boundaries."""
    import re

    text = text.replace("\n", " ").strip()
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw if s.strip()]
