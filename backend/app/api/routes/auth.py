import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core.config import settings
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
    create_reset_token,
    create_verify_token,
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

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=email,
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
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None

    verify_token = create_verify_token(email)
    # TODO: send verification email with link containing verify_token
    logger.info("Email verification token generated for %s", email)

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
    # TODO: send verification email
    logger.info("Resent verification token for %s", current_user.email)

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
    email = body.email.lower()
    await check_account_rate_limit(email)

    result = await db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
    user = result.scalar_one_or_none()

    # Always run bcrypt to prevent timing side-channel that reveals whether the email exists
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
        _token = create_reset_token(email)  # noqa: F841 — will be used when email sending is implemented
        # TODO: send email with reset link containing _token
        logger.info("Password reset token generated for %s", body.email)

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


# ── OAuth placeholder (future: Google / Apple) ────────────────────────────────
@router.get("/oauth/{provider}")
async def oauth_redirect(provider: str):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OAuth coming soon")
