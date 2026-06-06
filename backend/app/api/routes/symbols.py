import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.api.deps import get_db, require_tier
from app.models.symbol_request import SymbolRequest
from app.models.ticker import Ticker
from app.models.user import User
from app.schemas.symbol_request import (
    SymbolRequestInput,
    SymbolRequestResult,
    SymbolRequestRow,
)

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


@router.post("/request", response_model=SymbolRequestResult)
async def request_symbol(
    payload: SymbolRequestInput,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Record demand for a symbol we don't cover.

    Deduped by symbol (PK) — repeat requests just bump ``request_count``. A
    background job (``ml.tasks.symbol_validation``) later classifies it via
    Massive. No free text reaches any LLM; this only touches the relational DB.
    """
    symbol = payload.symbol
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid symbol format",
        )

    # Already in our universe → nothing to request.
    existing = await db.get(Ticker, symbol)
    if existing is not None and existing.is_active:
        return SymbolRequestResult(
            symbol=symbol,
            status="already_covered",
            request_count=0,
            message=f"{symbol} is already covered by PenguinAI.",
        )

    # Upsert: insert new (count=1) or increment + refresh last_requested_at.
    stmt = (
        pg_insert(SymbolRequest)
        .values(symbol=symbol, request_count=1, status="pending")
        .on_conflict_do_update(
            index_elements=[SymbolRequest.symbol],
            set_={
                "request_count": SymbolRequest.request_count + 1,
                "last_requested_at": func.now(),
            },
        )
        .returning(SymbolRequest.request_count, SymbolRequest.status)
    )
    result = await db.execute(stmt)
    row = result.one()

    return SymbolRequestResult(
        symbol=symbol,
        status=row.status,
        request_count=row.request_count,
        message=(
            f"Thanks — we logged your request for {symbol} and will review adding it."
        ),
    )


@router.get("/requests", response_model=list[SymbolRequestRow])
async def list_symbol_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(require_tier("ADMIN"))],
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
):
    """Admin: inspect the data-demand queue, most-requested first."""
    q = select(SymbolRequest)
    if status_filter:
        q = q.where(SymbolRequest.status == status_filter)
    q = q.order_by(SymbolRequest.request_count.desc()).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()
