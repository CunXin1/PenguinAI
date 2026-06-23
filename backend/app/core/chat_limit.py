"""Per-user, tier-based quota for the chat assistant.

Unlike the per-IP :class:`~app.core.rate_limit.RateLimit` dependency, chat is
metered per authenticated user — a fixed window keyed by user id with
tier-specific allowances (FREE limited, PRO higher, PREMIUM/ADMIN unlimited).
Backed by the same Redis pool; if Redis is down chat is allowed through
(fail-open), matching the rest of the rate-limit layer.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.rate_limit import _get_redis
from app.models.user import User

logger = logging.getLogger(__name__)

_KEY = "rl:chat:{uid}"


def _limit_for(tier: str) -> int:
    """Messages allowed per window for a tier. 0 means unlimited."""
    if tier in ("PREMIUM", "ADMIN"):
        return settings.CHAT_LIMIT_PREMIUM  # 0 = unlimited
    if tier == "PRO":
        return settings.CHAT_LIMIT_PRO
    return settings.CHAT_LIMIT_FREE


def _snapshot(tier: str, used: int, ttl: int) -> dict:
    """Build the usage dict consumed by app.schemas.chat.ChatUsage."""
    limit = _limit_for(tier)
    window = settings.CHAT_WINDOW_SECONDS
    if limit <= 0:  # unlimited
        return {
            "tier": tier,
            "limit": 0,
            "remaining": -1,
            "reset_seconds": 0,
            "window_seconds": window,
        }
    return {
        "tier": tier,
        "limit": limit,
        "remaining": max(0, limit - used),
        "reset_seconds": max(0, ttl),
        "window_seconds": window,
    }


async def peek_quota(user: User) -> dict:
    """Current quota snapshot without consuming. Backs GET /api/chat/quota."""
    if _limit_for(user.tier) <= 0:
        return _snapshot(user.tier, 0, 0)
    redis = await _get_redis()
    if redis is None:
        return _snapshot(user.tier, 0, 0)
    key = _KEY.format(uid=user.id)
    try:
        used = int(await redis.get(key) or 0)
        ttl = await redis.ttl(key)
    except Exception:
        logger.warning("Chat quota peek failed — reporting full quota", exc_info=True)
        return _snapshot(user.tier, 0, 0)
    return _snapshot(user.tier, used, ttl if ttl and ttl > 0 else 0)


async def consume_quota(user: User) -> dict:
    """Consume one message; raise 429 if the window is exhausted.

    Metered *before* the model is called so a rejected request never reaches the
    LLM. Returns the post-consumption snapshot. Fail-open if Redis is down.
    """
    limit = _limit_for(user.tier)
    if limit <= 0:  # unlimited tiers never touch Redis
        return _snapshot(user.tier, 0, 0)
    redis = await _get_redis()
    if redis is None:
        return _snapshot(user.tier, 0, 0)  # fail-open

    key = _KEY.format(uid=user.id)
    try:
        used = await redis.incr(key)
        ttl = await redis.ttl(key)
        # Always ensure the counter has a TTL. If the first INCR's EXPIRE was ever lost
        # (crash/Redis hiccup), ttl is -1 (key, no expiry) and the user would be locked
        # out forever; re-arm the window. ttl == -2 (no key) can't happen right after INCR.
        if used == 1 or ttl < 0:
            await redis.expire(key, settings.CHAT_WINDOW_SECONDS)
            ttl = settings.CHAT_WINDOW_SECONDS
    except Exception:
        logger.warning("Chat quota consume failed — allowing message", exc_info=True)
        return _snapshot(user.tier, 0, 0)

    if used > limit:
        retry = ttl if ttl and ttl > 0 else settings.CHAT_WINDOW_SECONDS
        hours = settings.CHAT_WINDOW_SECONDS // 3600
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Chat limit reached for the {user.tier} plan "
                f"({limit} messages per {hours}h). "
                f"Try again in about {max(retry // 60, 1)} min, or upgrade your plan."
            ),
            headers={"Retry-After": str(max(retry, 1))},
        )
    return _snapshot(user.tier, used, ttl if ttl and ttl > 0 else 0)


async def refund_quota(user: User) -> None:
    """Best-effort: return one consumed message (used when generation fails so a
    server-side error doesn't cost the user a message)."""
    if _limit_for(user.tier) <= 0:
        return
    redis = await _get_redis()
    if redis is None:
        return
    key = _KEY.format(uid=user.id)
    try:
        if int(await redis.get(key) or 0) > 0:
            await redis.decr(key)
    except Exception:
        logger.warning("Chat quota refund failed", exc_info=True)
