import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

_PASSWORD_MIN = 8
_PASSWORD_MAX = 72  # bcrypt limit


def _validate_password_strength(password: str) -> str:
    if len(password) < _PASSWORD_MIN:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN} characters")
    if len(password) > _PASSWORD_MAX:
        raise ValueError(f"Password must be at most {_PASSWORD_MAX} characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain at least one special character")
    return password


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


def _validate_username(username: str) -> str:
    username = username.strip()
    if not _USERNAME_RE.match(username):
        raise ValueError("Username must be 3-20 characters: letters, digits, or underscore")
    return username


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    display_name: str | None = Field(default=None, max_length=50)

    @field_validator("username")
    @classmethod
    def username_format(cls, v: str) -> str:
        return _validate_username(v)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)  # email or username
    password: str = Field(max_length=_PASSWORD_MAX)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class RegisterResponse(BaseModel):
    message: str
    email: str


class UserResponse(BaseModel):
    id: str
    email: str
    username: str | None
    display_name: str | None
    tier: Literal["FREE", "PRO", "PREMIUM", "ADMIN"]
    email_verified: bool
    oauth_provider: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: object) -> str:
        return str(v)
