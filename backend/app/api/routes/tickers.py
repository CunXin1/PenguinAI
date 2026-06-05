from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.ticker import Ticker
from app.schemas.ticker import TickerResponse, TickerSearchResult

router = APIRouter()


@router.get("/search", response_model=list[TickerSearchResult])
async def search_tickers(
    q: str = Query(min_length=1, max_length=20),
    db: AsyncSession = Depends(get_db),
):
    q_upper = q.upper()
    result = await db.execute(
        select(Ticker)
        .where(
            Ticker.is_active.is_(True),
            or_(
                Ticker.ticker.ilike(f"{q_upper}%"),
                Ticker.name.ilike(f"%{q}%"),
            ),
        )
        .order_by(Ticker.market_cap.desc().nullslast())
        .limit(20)
    )
    return result.scalars().all()


@router.get("/universe", response_model=list[TickerResponse])
async def get_universe(
    db: AsyncSession = Depends(get_db),
    sector: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
):
    q = select(Ticker).where(Ticker.is_active.is_(True))
    if sector:
        q = q.where(Ticker.sector == sector)
    if tag:
        q = q.where(Ticker.tags.any(tag))
    q = q.order_by(Ticker.market_cap.desc().nullslast()).offset(offset).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{ticker}", response_model=TickerResponse)
async def get_ticker(ticker: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(Ticker, ticker.upper())
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticker not found")
    return row
