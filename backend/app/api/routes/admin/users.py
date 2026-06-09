from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier
from app.models.user import User

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))

_VALID_TIERS = {"FREE", "PRO", "PREMIUM", "ADMIN"}


@router.get("/stats")
async def user_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
):
    """Aggregate user statistics."""
    result = await db.execute(
        text("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE email_verified) AS verified,
                count(*) FILTER (WHERE is_active) AS active,
                count(*) FILTER (WHERE created_at >= now() - interval '1 day') AS today,
                count(*) FILTER (WHERE created_at >= now() - interval '7 days') AS this_week
            FROM users
        """)
    )
    row = result.mappings().one()

    tier_result = await db.execute(
        text("SELECT tier, count(*) AS cnt FROM users GROUP BY tier")
    )
    by_tier = {r["tier"]: int(r["cnt"]) for r in tier_result.mappings().all()}

    return {
        "total": int(row["total"]),
        "by_tier": by_tier,
        "verified": int(row["verified"]),
        "active": int(row["active"]),
        "registered_today": int(row["today"]),
        "registered_this_week": int(row["this_week"]),
    }


@router.get("")
async def user_list(
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    tier: str = Query(""),
):
    """Paginated user list with search and tier filter."""
    q = select(User)
    count_q = select(func.count(User.id))

    if search:
        pattern = f"%{search}%"
        q = q.where(User.email.ilike(pattern) | User.display_name.ilike(pattern))
        count_q = count_q.where(User.email.ilike(pattern) | User.display_name.ilike(pattern))

    if tier and tier in _VALID_TIERS:
        q = q.where(User.tier == tier)
        count_q = count_q.where(User.tier == tier)

    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    q = q.order_by(User.created_at.desc())
    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    users = result.scalars().all()

    return {
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
                "tier": u.tier,
                "is_active": u.is_active,
                "email_verified": u.email_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_tier("ADMIN"))],
    tier: str | None = None,
    is_active: bool | None = None,
):
    """Update a user's tier or active status. Cannot modify self."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    if uid == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify your own account via admin",
        )

    result = await db.execute(select(User).where(User.id == uid))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if tier is not None:
        if tier not in _VALID_TIERS:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
        target.tier = tier

    if is_active is not None:
        target.is_active = is_active

    await db.flush()
    return {
        "id": str(target.id),
        "email": target.email,
        "tier": target.tier,
        "is_active": target.is_active,
    }
