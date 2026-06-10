import json
import logging
import re
import secrets
from typing import Annotated
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core import oauth as oauthlib
from app.core.config import settings
from app.core.email import send_password_reset_email, send_verification_email
from app.core.rate_limit import (
    check_account_rate_limit,
    forgot_password_rate_limit,
    login_rate_limit,
    register_rate_limit,
    reset_password_rate_limit,
)
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    create_oauth_state_token,
    create_reset_token,
    create_verify_token,
    decode_oauth_state_token,
    decode_reset_token,
    decode_verify_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rl: Annotated[None, Depends(register_rate_limit)],
):
    email = body.email.lower()
    username = body.username.strip()

    existing = await db.execute(
        select(User).where(
            or_(User.email == email, func.lower(User.username) == username.lower())
        )
    )
    dup = existing.scalars().first()
    if dup:
        detail = "Email already registered" if dup.email == email else "Username already taken"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        tier="FREE",
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        ) from None

    verify_token = create_verify_token(email)
    await send_verification_email(email, verify_token)

    access_token = create_access_token(str(user.id), user.token_version)
    resp: dict = {"access_token": access_token, "token_type": "bearer"}
    if settings.DEBUG:
        resp["_debug_verify_token"] = verify_token
    return resp


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    body: VerifyEmailRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    email = decode_verify_token(body.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link",
        )

    if user.email_verified:
        return {"message": "Email already verified."}

    user.email_verified = True
    await db.flush()

    return {"message": "Email verified successfully."}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
async def resend_verification(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.email_verified:
        return {"message": "Email already verified."}

    verify_token = create_verify_token(current_user.email)
    await send_verification_email(current_user.email, verify_token)

    resp: dict = {"message": "Verification email sent."}
    if settings.DEBUG:
        resp["_debug_verify_token"] = verify_token
    return resp


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rl: Annotated[None, Depends(login_rate_limit)],
):
    identifier = body.identifier.strip().lower()
    await check_account_rate_limit(identifier)

    result = await db.execute(
        select(User).where(
            or_(func.lower(User.email) == identifier, func.lower(User.username) == identifier),
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()

    # Always run bcrypt to prevent a timing side-channel that reveals whether the account exists
    hashed = user.password_hash if (user and user.password_hash) else DUMMY_HASH
    password_ok = verify_password(body.password, hashed)
    if not user or not user.password_hash or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(access_token=create_access_token(str(user.id), user.token_version))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    return current_user


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rl: Annotated[None, Depends(forgot_password_rate_limit)],
):
    email = body.email.lower()
    result = await db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
    user = result.scalar_one_or_none()

    if user:
        reset_token = create_reset_token(email)
        await send_password_reset_email(email, reset_token)

    return {"message": "If this email is registered, you will receive a reset link shortly."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rl: Annotated[None, Depends(reset_password_rate_limit)],
):
    email = decode_reset_token(body.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link",
        )

    result = await db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link",
        )

    user.password_hash = hash_password(body.password)
    user.token_version += 1
    await db.flush()

    return {"message": "Password has been reset successfully."}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not current_user.password_hash or not verify_password(
        body.current_password, current_user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(body.new_password)
    current_user.token_version += 1
    await db.flush()

    new_token = create_access_token(str(current_user.id), current_user.token_version)
    return {"message": "Password changed successfully.", "access_token": new_token}


# ── OAuth (Google + Apple "Sign in with") ─────────────────────────────────────
def _frontend_callback(**fragment: str) -> RedirectResponse:
    """Hand the result to the SPA via the URL fragment.

    The token rides in the fragment (``#``) rather than the query string so it is
    never sent to the server, logged, or leaked through the Referer header.
    """
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    return RedirectResponse(f"{base}/auth/callback#{urlencode(fragment)}", status_code=302)


@router.get("/oauth/{provider}")
async def oauth_start(provider: str):
    p = oauthlib.get_provider(provider)
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown OAuth provider")
    if not oauthlib.is_configured(p):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider.capitalize()} sign-in is not configured",
        )
    nonce = secrets.token_urlsafe(16)
    state = create_oauth_state_token(provider, nonce)
    return RedirectResponse(oauthlib.build_authorize_url(p, state, nonce), status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback_get(
    provider: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    return await _complete_oauth(provider, db, code, state, error, user_payload=None)


@router.post("/oauth/{provider}/callback")
async def oauth_callback_post(
    provider: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Apple uses response_mode=form_post → an application/x-www-form-urlencoded body
    # (and the one-time `user` display-name payload only on first consent). Parse it
    # directly so this path doesn't depend on python-multipart being installed.
    raw = (await request.body()).decode("utf-8")
    form = {key: values[0] for key, values in parse_qs(raw).items()}
    return await _complete_oauth(
        provider,
        db,
        code=form.get("code"),
        state=form.get("state"),
        error=form.get("error"),
        user_payload=form.get("user"),
    )


def _display_name(provider: str, claims: dict, user_payload: str | None, email: str) -> str:
    if provider == "google":
        return claims.get("name") or email.split("@")[0]
    # Apple: the name is delivered once, in the `user` form field, not in the id_token.
    if user_payload:
        try:
            name = (json.loads(user_payload).get("name") or {}) if user_payload else {}
            full = f"{name.get('firstName', '')} {name.get('lastName', '')}".strip()
            if full:
                return full
        except (ValueError, TypeError):
            pass
    return email.split("@")[0]


async def _unique_username(db: AsyncSession, email: str) -> str:
    """Derive a unique handle from an OAuth email (sanitized local-part + numeric suffix)."""
    base = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower())[:16] or "user"
    if len(base) < 3:
        base = f"{base}user"[:16]
    candidate, suffix = base, 0
    while True:
        taken = await db.execute(
            select(User.id).where(func.lower(User.username) == candidate.lower())
        )
        if taken.scalar_one_or_none() is None:
            return candidate
        suffix += 1
        candidate = f"{base}{suffix}"


async def _find_or_create_oauth_user(
    db: AsyncSession,
    provider: str,
    sub: str,
    email: str,
    email_verified: bool,
    display_name: str,
) -> User:
    # 1) Returning OAuth user — match on the stable provider subject.
    result = await db.execute(
        select(User).where(User.oauth_provider == provider, User.oauth_sub == sub)
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    # 2) Existing email/password account with the same email → link this provider.
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        if not user.oauth_provider:
            user.oauth_provider = provider
            user.oauth_sub = sub
        if not user.username:
            user.username = await _unique_username(db, email)
        if email_verified and not user.email_verified:
            user.email_verified = True
        await db.flush()
        return user

    # 3) Brand-new user (OAuth emails are pre-verified by the provider).
    user = User(
        email=email,
        username=await _unique_username(db, email),
        password_hash=None,
        display_name=display_name,
        oauth_provider=provider,
        oauth_sub=sub,
        email_verified=email_verified,
        tier="FREE",
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Race: a concurrent callback created this user between our SELECT and INSERT.
        await db.rollback()
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            raise
    return user


async def _complete_oauth(
    provider: str,
    db: AsyncSession,
    code: str | None,
    state: str | None,
    error: str | None,
    user_payload: str | None,
) -> RedirectResponse:
    p = oauthlib.get_provider(provider)
    if not p or not oauthlib.is_configured(p):
        return _frontend_callback(error="oauth_unavailable")
    if error or not code or not state:
        return _frontend_callback(error=error or "oauth_cancelled")

    state_data = decode_oauth_state_token(state)
    if not state_data or state_data.get("provider") != provider:
        return _frontend_callback(error="invalid_state")
    nonce = state_data.get("nonce", "")

    try:
        token = await oauthlib.exchange_code(p, code)
        id_token = token.get("id_token")
        if not id_token:
            raise oauthlib.OAuthError("token response had no id_token")
        claims = await oauthlib.verify_id_token(p, id_token, nonce)
    except oauthlib.OAuthError as exc:
        logger.warning("OAuth %s callback failed: %s", provider, exc)
        return _frontend_callback(error="oauth_failed")

    sub = claims.get("sub")
    email = (claims.get("email") or "").lower()
    if not sub or not email:
        return _frontend_callback(error="oauth_no_email")
    email_verified = claims.get("email_verified") in (True, "true")
    display_name = _display_name(provider, claims, user_payload, email)

    user = await _find_or_create_oauth_user(db, provider, sub, email, email_verified, display_name)
    logger.info("OAuth %s sign-in for %s", provider, email)
    access_token = create_access_token(str(user.id), user.token_version)
    return _frontend_callback(access_token=access_token)
