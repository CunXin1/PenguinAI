from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.signal_cache import SignalCache
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.schemas.signal import SignalListItem

router = APIRouter()


@router.get("", response_model=list[dict])
async def get_watchlist(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return user's watchlist tickers with their latest cached signals."""
    result = await db.execute(select(Watchlist.ticker).where(Watchlist.user_id == current_user.id))
    tickers = [row[0] for row in result.all()]
    if not tickers:
        return []

    now = datetime.now(UTC)
    signals_result = await db.execute(
        select(SignalCache).where(
            SignalCache.ticker.in_(tickers),
            SignalCache.expires_at > now,
        )
    )
    signal_map = {s.ticker: s for s in signals_result.scalars().all()}

    return [
        {
            "ticker": t,
            "signal": SignalListItem.model_validate(signal_map[t]).model_dump()
            if t in signal_map
            else None,
        }
        for t in tickers
    ]


@router.post("/{ticker}", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    ticker: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ticker = ticker.upper()
    ticker_row = await db.get(Ticker, ticker)
    if not ticker_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticker not found")

    existing = await db.get(Watchlist, {"user_id": current_user.id, "ticker": ticker})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already in watchlist")

    db.add(Watchlist(user_id=current_user.id, ticker=ticker))
    return {"ticker": ticker, "added": True}


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    ticker: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await db.execute(
        delete(Watchlist).where(
            Watchlist.user_id == current_user.id,
            Watchlist.ticker == ticker.upper(),
        )
    )
