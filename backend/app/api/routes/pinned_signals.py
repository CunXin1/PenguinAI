from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.pinned_signal import PinnedSignal
from app.models.ticker import Ticker

router = APIRouter()

MAX_PINNED = 12


class PinnedTickersBody(BaseModel):
    tickers: list[str]

    @field_validator("tickers")
    @classmethod
    def validate_tickers(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_PINNED:
            raise ValueError(f"at most {MAX_PINNED} tickers allowed")
        seen: set[str] = set()
        out: list[str] = []
        for t in v:
            upper = t.upper()
            if upper not in seen:
                seen.add(upper)
                out.append(upper)
        return out


@router.get("", response_model=list[str])
async def get_pinned(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(PinnedSignal.ticker)
        .where(PinnedSignal.user_id == current_user.id)
        .order_by(PinnedSignal.position)
    )
    return [row[0] for row in result.all()]


@router.put("", response_model=list[str])
async def set_pinned(
    body: PinnedTickersBody,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    valid: list[str] = []
    for t in body.tickers:
        row = await db.get(Ticker, t)
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticker {t} not found",
            )
        valid.append(t)

    await db.execute(
        delete(PinnedSignal).where(PinnedSignal.user_id == current_user.id)
    )
    for i, t in enumerate(valid):
        db.add(PinnedSignal(user_id=current_user.id, ticker=t, position=i))

    return valid
