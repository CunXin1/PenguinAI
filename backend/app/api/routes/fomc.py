"""
FOMC API — statements, hawk/dove scores, meeting schedule, rate history,
market reactions, statement diffs, Fed news, and CME FedWatch probabilities.

Reads from the ``fomc_statements`` table (populated by ``data.fomc.loader``).
Rate history from ``data.fomc.fed_funds_rate`` (hardcoded, cross-verified).
Market reactions from ``bars_1d`` (SPY daily bars).
"""

import contextlib
import difflib
import logging
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from data.fomc.meetings import FOMC_MEETINGS, next_meeting_date

router = APIRouter()
logger = logging.getLogger(__name__)

# FOMC_MEETINGS / next_meeting_date come from data/fomc/meetings.py — the single
# source of truth shared with the data-layer scheduler so the two never drift.

_cache: dict[str, tuple[float, object]] = {}
_STATEMENTS_TTL = 3600.0
_NEWS_TTL = 900.0
_FEDWATCH_TTL = 1800.0


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
    limit: int = Query(default=None, ge=1, le=200),
):
    """All FOMC statements with hawk/dove scores, most recent first."""
    if limit is None:
        limit = settings.FOMC_DEFAULT_STATEMENTS_LIMIT
    cache_key = f"fomc:statements:{limit}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    try:
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
    except Exception:
        logger.warning("FOMC /statements DB query failed", exc_info=True)
        return []  # don't cache the failure — retry on next request
    _set_cache(cache_key, result)
    return result


@router.get("/trend")
async def get_fomc_trend(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=None, ge=1, le=50),
):
    """Hawk/dove score time-series for chart visualization (oldest first)."""
    if limit is None:
        limit = settings.FOMC_DEFAULT_TREND_LIMIT
    cache_key = f"fomc:trend:{limit}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    try:
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
                with contextlib.suppress(ValueError, TypeError):
                    date_str = datetime.fromisoformat(str(ts)).strftime("%Y-%m-%d")
            points.append({"date": date_str, "score": float(score)})
    except Exception:
        logger.warning("FOMC /trend DB query failed", exc_info=True)
        return []

    points.reverse()
    _set_cache(cache_key, points)
    return points


@router.get("/next-meeting")
async def get_next_meeting():
    """Next scheduled FOMC meeting date and countdown."""
    now = datetime.now(UTC)
    next_date = next_meeting_date()

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
async def get_fomc_schedule(
    past: int = Query(default=None, ge=0, le=50),
    future: int = Query(default=None, ge=0, le=50),
):
    """FOMC meeting schedule with configurable past/future window."""
    if past is None:
        past = settings.FOMC_DEFAULT_SCHEDULE_PAST
    if future is None:
        future = settings.FOMC_DEFAULT_SCHEDULE_FUTURE

    now_str = datetime.now(UTC).strftime("%Y-%m-%d")
    past_meetings = [d for d in FOMC_MEETINGS if d < now_str]
    future_meetings = [d for d in FOMC_MEETINGS if d >= now_str]

    selected_past = past_meetings[-past:] if past > 0 else []
    selected_future = future_meetings[:future] if future > 0 else []

    return [
        {"date": d, "past": d < now_str}
        for d in selected_past + selected_future
    ]


@router.get("/rate-history")
async def get_rate_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    years: int = Query(default=None, ge=1, le=30),
):
    """Federal funds rate over time — from fomc_fed_funds_rate table.

    Data is populated by the FOMC scheduler (FRED API or hardcoded seed).
    Falls back to the hardcoded table if the DB table is empty.
    """
    if years is None:
        years = settings.FOMC_DEFAULT_RATE_HISTORY_YEARS
    cache_key = f"fomc:rate-history:{years}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    now = datetime.now(UTC)
    cutoff_year = now.year - years
    cutoff_str = f"{cutoff_year}-{now.month:02d}-{now.day:02d}"

    points: list[dict] = []
    try:
        rows = await db.execute(
            text(
                "SELECT date, rate_low, rate_high "
                "FROM fomc_fed_funds_rate "
                "WHERE date >= :cutoff "
                "ORDER BY date"
            ),
            {"cutoff": cutoff_str},
        )
        points = [
            {
                "date": str(r["date"]),
                "rate_low": float(r["rate_low"]),
                "rate_high": float(r["rate_high"]),
            }
            for r in rows.mappings()
        ]
    except Exception:
        logger.debug("fomc_fed_funds_rate table not available, using hardcoded fallback")

    # Fallback to hardcoded if DB table is empty or missing
    if not points:
        from data.fomc.fed_funds_rate import FED_FUNDS_RATE_HISTORY

        for date_str in sorted(FED_FUNDS_RATE_HISTORY.keys()):
            if date_str < cutoff_str:
                continue
            low, high = FED_FUNDS_RATE_HISTORY[date_str]
            points.append({"date": date_str, "rate_low": low, "rate_high": high})

    _set_cache(cache_key, points)
    return points


@router.get("/market-reaction")
async def get_market_reaction(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=None, ge=1, le=100),
):
    """SPY return on each FOMC meeting day (intraday: close/prev_close - 1).

    Only returns dates where both the FOMC statement AND SPY daily bar exist.
    """
    if limit is None:
        limit = settings.FOMC_DEFAULT_MARKET_REACTION_LIMIT
    cache_key = f"fomc:market-reaction:{limit}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    try:
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
    except Exception:
        logger.warning("FOMC /market-reaction query failed", exc_info=True)
        return []

    _set_cache(cache_key, result)
    return result


@router.get("/diff")
async def get_statement_diff(
    db: Annotated[AsyncSession, Depends(get_db)],
    date: str = Query(..., description="Date of the statement to diff (YYYY-MM-DD)"),
):
    """Sentence-level diff between a statement and the previous one."""
    cache_key = f"fomc:diff:{date}"
    cached = _get_cached(cache_key, _STATEMENTS_TTL)
    if cached is not None:
        return cached

    from datetime import date as date_type

    try:
        target = date_type.fromisoformat(date)
    except ValueError:
        return {"error": "Invalid date format, use YYYY-MM-DD", "date": date}

    try:
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
    except Exception:
        logger.warning("FOMC /diff DB query failed", exc_info=True)
        return {"error": "Statement data temporarily unavailable", "date": date}

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


@router.get("/news")
async def get_fomc_news(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=10, ge=1, le=50),
):
    """Fed/FOMC-related news from DB (populated by scheduler), fallback to RSS."""
    cache_key = f"fomc:news:{limit}"
    cached = _get_cached(cache_key, _NEWS_TTL)
    if cached is not None:
        return cached[:limit]

    # Try DB first (scheduler populates news_articles with ticker='FOMC')
    articles: list[dict] = []
    try:
        rows = await db.execute(
            text(
                "SELECT id, time, headline, source, url, finbert_score, finbert_label, raw_metadata "
                "FROM news_articles "
                "WHERE ticker = 'FOMC' "
                "ORDER BY time DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        )
        for r in rows.mappings():
            ts = r["time"]
            unix_ts = int(ts.timestamp()) if isinstance(ts, datetime) else 0
            # Surface the FinBERT sentiment the table already stores (mirrors
            # news._map_db_row): prefer the label, else derive from the score.
            fb_score = r.get("finbert_score")
            fb_label = r.get("finbert_label")
            sentiment = None
            if fb_label in ("positive", "negative", "neutral"):
                sentiment = fb_label
            elif fb_score is not None:
                s = float(fb_score)
                sentiment = "positive" if s > 0.1 else "negative" if s < -0.1 else "neutral"
            articles.append({
                "id": str(r["id"]),
                "headline": r["headline"],
                "summary": "",
                "source": r["source"] or "Google News",
                "url": r.get("url"),
                "datetime": unix_ts,
                "tickers": [],
                "sentiment": sentiment,
                "sentiment_score": float(fb_score) if fb_score is not None else None,
            })
    except Exception:
        logger.debug("FOMC news DB query failed, using RSS fallback")

    # Fallback to live RSS if DB is empty or query failed
    if not articles:
        try:
            from app.api.routes.news import _fetch_google_rss

            articles = await _fetch_google_rss(
                query="Federal Reserve FOMC interest rate decision",
                limit=limit,
            ) or []
        except Exception:
            logger.warning("FOMC news RSS fallback failed", exc_info=True)

    _set_cache(cache_key, articles)
    return articles[:limit]


@router.get("/rate-probabilities")
async def get_rate_probabilities(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """CME FedWatch probabilities from DB (populated by scheduler), fallback to live."""
    cache_key = "fomc:rate-probs"
    cached = _get_cached(cache_key, _FEDWATCH_TTL)
    if cached is not None:
        return cached

    # Try DB first — get latest snapshot for the next meeting
    result: list[dict] = []
    try:
        rows = await db.execute(
            text("""
                SELECT DISTINCT ON (target_rate_low)
                    meeting_date, target_rate_low, target_rate_high, probability
                FROM fomc_rate_probabilities
                WHERE meeting_date >= CURRENT_DATE
                ORDER BY target_rate_low, time DESC
            """)
        )
        for r in rows.mappings():
            result.append({
                "meeting_date": str(r["meeting_date"]),
                "target_rate_low": float(r["target_rate_low"]),
                "target_rate_high": float(r["target_rate_high"]),
                "probability": float(r["probability"]),
            })
    except Exception:
        logger.debug("fomc_rate_probabilities table not available, using live fallback")

    # Fallback to live fetch if DB is empty or table missing
    if not result:
        try:
            from data.fomc.fedwatch import fetch_fedwatch_probabilities

            result = await fetch_fedwatch_probabilities() or []
        except Exception:
            logger.warning("CME FedWatch fetch failed", exc_info=True)
        # The live scraper may omit meeting_date; backfill with the next
        # scheduled FOMC meeting so the response shape stays consistent.
        next_mtg = next_meeting_date()
        for item in result:
            if not item.get("meeting_date"):
                item["meeting_date"] = next_mtg

    if result:
        result.sort(key=lambda x: x["probability"], reverse=True)
        _set_cache(cache_key, result)
    return result


def _split_sentences(text: str) -> list[str]:
    """Split statement text into sentences, preserving meaningful boundaries."""
    import re

    text = text.replace("\n", " ").strip()
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw if s.strip()]
