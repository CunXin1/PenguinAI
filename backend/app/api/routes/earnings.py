import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
_SESSION = {"bmo": "BMO", "amc": "AMC"}

_SELECT = """
    SELECT e.ticker, e.report_date, e.fiscal_quarter, e.fiscal_year,
           e.eps_actual, e.eps_estimate, e.eps_surprise_pct,
           e.revenue_actual, e.revenue_estimate, e.guidance_text, e.report_hour, t.name
    FROM earnings e
    JOIN tickers t ON t.ticker = e.ticker
"""

_PRICES_SQL = """
    SELECT i.symbol AS ticker, b.ts::date AS trade_date,
           b.adj_open AS open, b.adj_close AS close
    FROM bars_1d b
    JOIN instruments i ON i.instrument_id = b.instrument_id
    WHERE i.symbol = ANY(:tickers)
      AND b.ts::date BETWEEN :start AND :end
    ORDER BY i.symbol, b.ts
"""


def _revenue_surprise(actual: int | None, estimate: int | None) -> float | None:
    if actual is None or estimate is None or estimate == 0:
        return None
    return round((actual - estimate) / abs(estimate) * 100.0, 2)


def _build_price_map(price_rows) -> dict[str, list[tuple[date, float, float]]]:
    """ticker -> sorted list of (trade_date, open, close)."""
    m: dict[str, list[tuple[date, float, float]]] = {}
    for r in price_rows:
        if r["open"] is None or r["close"] is None:
            continue
        m.setdefault(r["ticker"], []).append((r["trade_date"], float(r["open"]), float(r["close"])))
    return m


def _price_reaction(
    price_list: list[tuple[date, float, float]] | None,
    report_date: date,
    report_hour: str | None,
) -> tuple[float | None, float | None]:
    """Return (reaction_open_pct, reaction_close_pct) for a reported earnings event.

    BMO: reaction day = report_date.  prev_close = day before report_date.
    AMC/TBD: reaction day = first trading day after report_date.  prev_close = report_date.
    """
    if not price_list:
        return None, None

    by_date = {d: (o, c) for d, o, c in price_list}
    dates = sorted(by_date.keys())
    if not dates:
        return None, None

    is_bmo = (report_hour or "").strip().lower() == "bmo"

    if is_bmo:
        reaction_date = report_date
        prev_candidates = [d for d in dates if d < report_date]
        if not prev_candidates:
            return None, None
        prev_date = prev_candidates[-1]
    else:
        prev_date = report_date
        next_candidates = [d for d in dates if d > report_date]
        if not next_candidates:
            return None, None
        reaction_date = next_candidates[0]

    if prev_date not in by_date or reaction_date not in by_date:
        return None, None

    prev_close = by_date[prev_date][1]
    reaction_open = by_date[reaction_date][0]
    reaction_close = by_date[reaction_date][1]

    if not prev_close:
        return None, None

    open_pct = round((reaction_open / prev_close - 1) * 100, 2)
    close_pct = round((reaction_close / prev_close - 1) * 100, 2)
    return open_pct, close_pct


def _to_event(row, price_map: dict | None = None) -> dict:
    num = lambda v: float(v) if v is not None else None  # noqa: E731
    rev_actual = int(row["revenue_actual"]) if row["revenue_actual"] is not None else None
    rev_estimate = int(row["revenue_estimate"]) if row["revenue_estimate"] is not None else None

    open_pct, close_pct = None, None
    if price_map and row["eps_actual"] is not None:
        open_pct, close_pct = _price_reaction(
            price_map.get(row["ticker"]),
            row["report_date"],
            row["report_hour"],
        )

    fq = row["fiscal_quarter"]
    fy = row["fiscal_year"]
    return {
        "ticker": row["ticker"],
        "report_date": row["report_date"].isoformat(),
        "fiscal_quarter": int(fq) if fq is not None else None,
        "fiscal_year": int(fy) if fy is not None else None,
        "eps_actual": num(row["eps_actual"]),
        "eps_estimate": num(row["eps_estimate"]),
        "eps_surprise_pct": num(row["eps_surprise_pct"]),
        "revenue_actual": rev_actual,
        "revenue_estimate": rev_estimate,
        "revenue_surprise_pct": _revenue_surprise(rev_actual, rev_estimate),
        "guidance_text": row["guidance_text"],
        "name": row["name"],
        "session": _SESSION.get((row["report_hour"] or "").strip().lower(), "TBD"),
        "reaction_open_pct": open_pct,
        "reaction_close_pct": close_pct,
    }


async def _fetch_prices(db: AsyncSession, tickers: list[str], start: date, end: date) -> dict:
    if not tickers:
        return {}
    result = await db.execute(
        text(_PRICES_SQL),
        {"tickers": tickers, "start": start - timedelta(days=5), "end": end + timedelta(days=5)},
    )
    return _build_price_map(result.mappings())


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
    earnings = list(rows.mappings())
    reported_tickers = list({r["ticker"] for r in earnings if r["eps_actual"] is not None})
    price_map = await _fetch_prices(db, reported_tickers, start, end)
    return [_to_event(r, price_map) for r in earnings]


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
    earnings = list(rows.mappings())
    if not earnings:
        return []
    dates = [r["report_date"] for r in earnings]
    price_map = await _fetch_prices(db, [t], min(dates), max(dates))
    return [_to_event(r, price_map) for r in earnings]
