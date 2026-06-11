"""Billing / subscription endpoints.

Paid checkout is intentionally NOT implemented yet — the product owner (an F1
student) cannot collect payments, so the frontend shows "Coming Soon" on the
Pro checkout button. The only live path to a paid tier today is redeeming an
invite code (a private back door, see `settings.INVITE_CODES`).

Everything here is read-only with respect to money: no charges, no payment
provider, no order execution — consistent with the project's "signals only"
rule. Tier is read fresh from the DB on every request (see deps.require_tier),
so a successful redeem takes effect immediately with no token refresh needed.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core.config import settings
from app.core.rate_limit import RateLimit
from app.schemas.user import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Tier ordering — redeeming never downgrades an already-higher tier.
_TIER_RANK = {"FREE": 0, "PRO": 1, "PREMIUM": 2, "ADMIN": 3}


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class RedeemResponse(BaseModel):
    message: str
    tier: str
    user: UserResponse


@router.post("/redeem", response_model=RedeemResponse)
async def redeem_code(
    body: RedeemRequest,
    request: Request,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    # Brute-force guard: invite codes are secrets, so cap attempts per IP.
    _rl: None = Depends(RateLimit(times=10, window=3600, key_prefix="redeem")),
) -> RedeemResponse:
    code = body.code.strip()
    codes = settings.invite_code_map()

    target_tier = codes.get(code)
    if target_tier is None:
        # Don't reveal whether the code exists in another form.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite code.",
        )

    current_rank = _TIER_RANK.get(current_user.tier, 0)
    target_rank = _TIER_RANK.get(target_tier, 0)

    if target_rank <= current_rank:
        # Already at this tier or higher — accept idempotently, change nothing.
        return RedeemResponse(
            message=f"You're already on the {current_user.tier} plan.",
            tier=current_user.tier,
            user=UserResponse.model_validate(current_user),
        )

    previous = current_user.tier
    current_user.tier = target_tier
    await db.commit()
    await db.refresh(current_user)

    logger.info(
        "Invite code redeemed: user=%s %s -> %s", current_user.id, previous, target_tier
    )
    return RedeemResponse(
        message=f"Code accepted — welcome to {target_tier}!",
        tier=target_tier,
        user=UserResponse.model_validate(current_user),
    )
