import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OptionalUser, get_db
from app.models.signal_cache import SignalCache
from app.models.ticker import Ticker
from app.models.user import User
from app.schemas.signal import SignalListItem, SignalResponse

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def _validate_ticker(ticker: str) -> str:
    t = ticker.upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid ticker format"
        )
    return t


_celery_app = None
_inflight: dict[str, float] = {}
_INFLIGHT_TTL = 300.0  # don't re-trigger same ticker within 5 minutes


def _trigger_signal_computation(ticker: str) -> None:
    """Send Celery task by name string — no ML imports in the API process.
    Deduplicates: won't re-trigger the same ticker within _INFLIGHT_TTL seconds."""
    import time

    now = time.monotonic()
    prev = _inflight.get(ticker)
    if prev is not None and (now - prev) < _INFLIGHT_TTL:
        return

    global _celery_app  # noqa: PLW0603
    if _celery_app is None:
        from celery import Celery

        from app.core.config import settings

        _celery_app = Celery(broker=settings.REDIS_URL)

    _celery_app.send_task(
        "ml.tasks.hourly_signal_cache.compute_single_signal",
        args=[ticker],
        queue="ml_inference",
    )
    _inflight[ticker] = now


@router.get("/top", response_model=list[SignalListItem])
async def get_top_signals(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, le=200),
):
    """Return pre-computed Top-N signals (cache hit, instant response)."""
    now = datetime.now(UTC)
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
    current_user: OptionalUser,
    poll: bool = False,
):
    """
    Return signal for a ticker.
    - Not in universe → 404 (reason: not_in_universe | delisted) — no compute fired
    - Cache hit       → 200 with signal (top-100 pre-computed, instant)
    - Cache miss      → 202, triggers background computation, frontend polls

    ``poll=true`` only checks the cache without re-triggering computation — the
    frontend uses it for follow-up polls so a single cold ticker doesn't queue a
    duplicate compute job on every poll.
    """
    ticker = _validate_ticker(ticker)
    now = datetime.now(UTC)

    # Universe gate: only symbols we actually cover can produce a signal. This
    # both prevents misleading output for junk symbols and stops us from firing
    # Celery compute jobs (and 202-polling forever) on tickers with no data.
    instrument = await db.get(Ticker, ticker)
    if instrument is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": f"{ticker} is not in PenguinAI's coverage universe",
                "reason": "not_in_universe",
                "ticker": ticker,
            },
        )
    if not instrument.is_active:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": f"{ticker} is delisted or inactive",
                "reason": "delisted",
                "ticker": ticker,
            },
        )

    cached = await db.get(SignalCache, ticker)
    if cached and cached.expires_at > now:
        _check_tier_access(current_user, cached.tier_required)
        return SignalResponse.model_validate(cached)

    # Cache miss on a covered ticker: trigger computation asynchronously.
    # Follow-up polls (poll=true) skip the trigger — they just await the result.
    if not poll:
        _trigger_signal_computation(ticker)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Signal computation triggered", "ticker": ticker, "retry_after": 5},
    )


def _check_tier_access(user: User | None, required: str) -> None:
    """Anonymous callers are treated as FREE (rank 0)."""
    tier_rank = {"FREE": 0, "PRO": 1, "PREMIUM": 2, "ADMIN": 99}
    user_tier = user.tier if user else "FREE"
    if tier_rank.get(user_tier, 0) < tier_rank.get(required, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier '{required}' required",
        )
