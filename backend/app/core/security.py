import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# Use bcrypt directly rather than passlib: passlib 1.7.x crashes reading the
# version of bcrypt 4.x ("module 'bcrypt' has no attribute '__about__'"), which
# made every register/login 500. bcrypt's `$2b$` hashes are unchanged.


DUMMY_HASH = "$2b$12$L2N2PSbSpAa5..JY28ON6Ozf7rIp9lc0yiR9nHWNmH9iYC4QrD/IC"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str | Any, token_version: int = 0, expires_delta: timedelta | None = None
) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "ver": token_version, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return {}


def create_reset_token(email: str) -> str:
    expire = datetime.now(UTC) + timedelta(hours=1)
    payload = {"sub": email, "purpose": "reset", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_reset_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_verify_token(email: str) -> str:
    expire = datetime.now(UTC) + timedelta(hours=24)
    payload = {"sub": email, "purpose": "verify", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_verify_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "verify":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_oauth_state_token(provider: str, nonce: str) -> str:
    """Signed, short-lived CSRF/nonce carrier for the OAuth round-trip.

    Stateless by design: everything needed on callback (provider + the nonce that
    must match the id_token) is sealed in this token, so there is no server-side
    session or Redis entry to lose. Survives Apple's cross-site form_post callback
    where a SameSite cookie would not be sent.
    """
    expire = datetime.now(UTC) + timedelta(minutes=10)
    payload = {
        "provider": provider,
        "nonce": nonce,
        "csrf": secrets.token_urlsafe(8),
        "purpose": "oauth_state",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_oauth_state_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "oauth_state":
            return None
        return payload
    except JWTError:
        return None
