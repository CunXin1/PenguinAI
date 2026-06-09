import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
# Finnhub `hour` → frontend EarningsSession (display badge).
_SESSION = {"bmo": "BMO", "amc": "AMC"}

_SELECT = """
    SELECT e.ticker, e.report_date, e.eps_actual, e.eps_estimate, e.eps_surprise_pct,
           e.revenue_actual, e.revenue_estimate, e.guidance_text, e.report_hour, t.name
    FROM earnings e
    JOIN tickers t ON t.ticker = e.ticker
"""


def _to_event(row) -> dict:
    """Map an earnings row to the frontend `EarningsEvent` shape."""
    num = lambda v: float(v) if v is not None else None  # noqa: E731
    return {
        "ticker": row["ticker"],
        "report_date": row["report_date"].isoformat(),
        "eps_actual": num(row["eps_actual"]),
        "eps_estimate": num(row["eps_estimate"]),
        "eps_surprise_pct": num(row["eps_surprise_pct"]),
        "revenue_actual": int(row["revenue_actual"]) if row["revenue_actual"] is not None else None,
        "revenue_estimate": (
            int(row["revenue_estimate"]) if row["revenue_estimate"] is not None else None
        ),
        "guidance_text": row["guidance_text"],
        "name": row["name"],
        "session": _SESSION.get((row["report_hour"] or "").strip().lower(), "TBD"),
    }


@router.get("/calendar")
async def get_calendar(
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
):
    """Earnings calendar for a date window (defaults to today-7d .. today+30d)."""
    today = datetime.now(UTC).date()
    start = date_from or (today - timedelta(days=7))
    end = date_to or (today + timedelta(days=30))
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`to` must be on or after `from`",
        )

    rows = await db.execute(
        text(
            _SELECT
            + " WHERE e.report_date BETWEEN :start AND :end ORDER BY e.report_date, e.ticker"
        ),
        {"start": start, "end": end},
    )
    return [_to_event(r) for r in rows.mappings()]


@router.get("/{ticker}")
async def get_ticker_earnings(
    ticker: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=12, ge=1, le=40),
):
    """Most recent earnings history for one ticker (newest first)."""
    t = ticker.upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid ticker format"
        )
    rows = await db.execute(
        text(_SELECT + " WHERE e.ticker = :t ORDER BY e.report_date DESC LIMIT :limit"),
        {"t": t, "limit": limit},
    )
    return [_to_event(r) for r in rows.mappings()]
