import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db

router = APIRouter()

_CELEB_RE = re.compile(r"^[a-z_]{2,30}$")
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

_BASE_SELECT = """
    SELECT ch.id, ch.reported_at, ch.celebrity, ch.ticker, ch.action,
           ch.shares, ch.value_usd, ch.source_type, ch.filing_url,
           t.name AS ticker_name
    FROM celebrity_holdings ch
    JOIN tickers t ON t.ticker = ch.ticker
"""


def _to_holding(row) -> dict:
    return {
        "id": str(row["id"]),
        "reported_at": row["reported_at"].isoformat(),
        "celebrity": row["celebrity"],
        "ticker": row["ticker"],
        "ticker_name": row["ticker_name"],
        "action": row["action"],
        "shares": row["shares"],
        "value_usd": row["value_usd"],
        "source_type": row["source_type"],
        "filing_url": row["filing_url"],
    }


@router.get("/stats/summary")
async def get_stats(db: Annotated[AsyncSession, Depends(get_db)]):
    """Per-celebrity aggregate stats."""
    rows = await db.execute(
        text("""
        SELECT celebrity,
               COUNT(*)                                    AS total_trades,
               COUNT(*) FILTER (WHERE action = 'BUY')     AS buys,
               COUNT(*) FILTER (WHERE action = 'SELL')    AS sells,
               MAX(reported_at)                            AS latest_trade
        FROM celebrity_holdings
        GROUP BY celebrity
        ORDER BY latest_trade DESC
    """)
    )
    return [
        {
            "celebrity": r["celebrity"],
            "total_trades": r["total_trades"],
            "buys": r["buys"],
            "sells": r["sells"],
            "latest_trade": r["latest_trade"].isoformat() if r["latest_trade"] else None,
        }
        for r in rows.mappings()
    ]


@router.get("/ticker/{ticker}")
async def get_by_ticker(
    ticker: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
):
    """Celebrity transactions for a given ticker."""
    t = ticker.upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid ticker format"
        )
    rows = await db.execute(
        text(_BASE_SELECT + " WHERE ch.ticker = :t ORDER BY ch.reported_at DESC LIMIT :limit"),
        {"t": t, "limit": limit},
    )
    return [_to_holding(r) for r in rows.mappings()]


@router.get("/{celebrity}")
async def get_celebrity(
    celebrity: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
):
    """All trades for one celebrity."""
    c = celebrity.lower()
    if not _CELEB_RE.match(c):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid celebrity slug"
        )
    rows = await db.execute(
        text(_BASE_SELECT + " WHERE ch.celebrity = :c ORDER BY ch.reported_at DESC LIMIT :limit"),
        {"c": c, "limit": limit},
    )
    return [_to_holding(r) for r in rows.mappings()]


@router.get("")
async def list_holdings(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Recent transactions across all tracked celebrities."""
    rows = await db.execute(
        text(_BASE_SELECT + " ORDER BY ch.reported_at DESC LIMIT :limit OFFSET :offset"),
        {"limit": limit, "offset": offset},
    )
    return [_to_holding(r) for r in rows.mappings()]
