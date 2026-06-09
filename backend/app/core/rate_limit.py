"""
Redis-backed sliding-window rate limiter for FastAPI.

Usage as a dependency:

    from app.core.rate_limit import RateLimit

    @router.post("/login")
    async def login(
        request: Request,
        _rl: None = Depends(RateLimit(times=5, window=60)),
    ):
        ...

When Redis is unavailable (dev without Docker), requests pass through with a warning.
"""

import hashlib
import logging
import time

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.core.config import settings

_logger = logging.getLogger(__name__)

_pool: Redis | None = None
_last_connect_attempt: float = 0
_RETRY_COOLDOWN = 30.0


async def _get_redis() -> Redis | None:
    global _pool, _last_connect_attempt
    if _pool is not None:
        return _pool
    now = time.monotonic()
    if now - _last_connect_attempt < _RETRY_COOLDOWN:
        return None
    _last_connect_attempt = now
    try:
        conn = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await conn.ping()
        _pool = conn
        _logger.info("Redis connected — rate limiting active")
        return _pool
    except Exception:
        _logger.warning(
            "Redis unavailable — rate limiting disabled (retry in %ds)", int(_RETRY_COOLDOWN)
        )
        return None


class RateLimit:
    """Sliding-window rate limiter backed by Redis INCR + EXPIRE.

    Args:
        times:  max requests allowed in the window.
        window: window size in seconds.
        key_prefix: override the rate-limit bucket name.
    """

    def __init__(self, times: int = 5, window: int = 60, key_prefix: str = "rl"):
        self.times = times
        self.window = window
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> None:
        redis = await _get_redis()
        if redis is None:
            return

        ip = request.client.host if request.client else "unknown"
        key = f"{self.key_prefix}:{request.url.path}:{ip}"

        try:
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, self.window)
            if current > self.times:
                ttl = await redis.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Try again in {max(ttl, 1)} seconds.",
                    headers={"Retry-After": str(max(ttl, 1))},
                )
        except HTTPException:
            raise
        except Exception:
            _logger.warning("Rate limit check failed — allowing request", exc_info=True)


async def check_account_rate_limit(email: str) -> None:
    """Account-level rate limit keyed by email hash. Prevents distributed brute-force
    attacks where many IPs target the same account."""
    redis = await _get_redis()
    if redis is None:
        return
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    key = f"rl:account:{email_hash}"
    times = settings.RATE_LIMIT_ACCOUNT_LOGIN_TIMES
    window = settings.RATE_LIMIT_ACCOUNT_LOGIN_WINDOW
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window)
        if current > times:
            ttl = await redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts for this account. Try again in {max(ttl, 1)} seconds.",
                headers={"Retry-After": str(max(ttl, 1))},
            )
    except HTTPException:
        raise
    except Exception:
        _logger.warning("Account rate limit check failed — allowing request", exc_info=True)


login_rate_limit = RateLimit(
    times=settings.RATE_LIMIT_LOGIN_TIMES,
    window=settings.RATE_LIMIT_LOGIN_WINDOW,
    key_prefix="rl:login",
)
register_rate_limit = RateLimit(
    times=settings.RATE_LIMIT_REGISTER_TIMES,
    window=settings.RATE_LIMIT_REGISTER_WINDOW,
    key_prefix="rl:register",
)
forgot_password_rate_limit = RateLimit(
    times=settings.RATE_LIMIT_FORGOT_PW_TIMES,
    window=settings.RATE_LIMIT_FORGOT_PW_WINDOW,
    key_prefix="rl:forgot",
)
reset_password_rate_limit = RateLimit(
    times=settings.RATE_LIMIT_RESET_PW_TIMES,
    window=settings.RATE_LIMIT_RESET_PW_WINDOW,
    key_prefix="rl:reset",
)
