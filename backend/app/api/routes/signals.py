from datetime import datetime, timezone
from typing import Annotated

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.signal_cache import SignalCache
from app.models.user import User
from app.schemas.signal import SignalListItem, SignalResponse

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def _validate_ticker(ticker: str) -> str:
    t = ticker.upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid ticker format")
    return t


def _trigger_signal_computation(ticker: str) -> None:
    """Send Celery task by name string — no ML imports in the API process."""
    from celery import Celery
    from app.core.config import settings
    app = Celery(broker=settings.REDIS_URL)
    app.send_task(
        "ml.tasks.hourly_signal_cache.compute_single_signal",
        args=[ticker],
        queue="ml_inference",
    )


@router.get("/top", response_model=list[SignalListItem])
async def get_top_signals(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, le=200),
):
    """Return pre-computed Top-N signals (cache hit, instant response)."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SignalCache)
        .where(SignalCache.expires_at > now)
        .order_by(SignalCache.confidence.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{ticker}", response_model=SignalResponse)
async def get_signal(
    ticker: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
):
    """
    Return signal for a ticker.
    - Cache hit  → 200 with signal (top-100 pre-computed, instant)
    - Cache miss → 202, triggers background computation, frontend polls
    """
    ticker = _validate_ticker(ticker)
    now = datetime.now(timezone.utc)

    cached = await db.get(SignalCache, ticker)
    if cached and cached.expires_at > now:
        _check_tier_access(current_user, cached.tier_required)
        return cached

    # Cache miss: trigger computation asynchronously
    _trigger_signal_computation(ticker)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Signal computation triggered", "ticker": ticker, "retry_after": 5},
    )


def _check_tier_access(user: User, required: str) -> None:
    tier_rank = {"FREE": 0, "PRO": 1, "PREMIUM": 2, "ADMIN": 99}
    if tier_rank.get(user.tier, 0) < tier_rank.get(required, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier '{required}' required",
        )
