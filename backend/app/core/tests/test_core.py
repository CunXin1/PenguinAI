"""Module 6b: direct unit tests for market_clock, security, and config."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.core.market_clock import ET, get_market_status, is_regular_session
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

# ── market_clock: is_regular_session ─────────────────────────────


def test_regular_session_weekday_10am_et():
    # Wednesday 2026-06-10 at 10:00 ET = 14:00 UTC
    now_utc = datetime(2026, 6, 10, 14, 0, 0, tzinfo=UTC)
    assert is_regular_session(now_utc) is True


def test_regular_session_weekend_false():
    # Saturday 2026-06-13 at 10:00 ET = 14:00 UTC
    now_utc = datetime(2026, 6, 13, 14, 0, 0, tzinfo=UTC)
    assert is_regular_session(now_utc) is False


def test_regular_session_weekday_8pm_et_false():
    # Wednesday 2026-06-10 at 20:00 ET = 00:00 UTC next day
    now_utc = datetime(2026, 6, 11, 0, 0, 0, tzinfo=UTC)
    assert is_regular_session(now_utc) is False


# ── market_clock: get_market_status ──────────────────────────────


async def test_get_market_status_returns_dict():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = None
    mock_db.execute.return_value = mock_result

    result = await get_market_status(mock_db)

    assert isinstance(result, dict)
    assert "market_open" in result
    assert "session_open" in result
    assert "source" in result
    assert "as_of" in result
    assert "latest_tick" in result


# ── security: password hashing ───────────────────────────────────


def test_hash_and_verify_password_roundtrip():
    plain = "SuperSecret123!"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("correct-password")
    assert verify_password("wrong-password", hashed) is False


# ── security: JWT tokens ────────────────────────────────────────


def test_create_and_decode_access_token_roundtrip():
    subject = "test-user-id-123"
    token = create_access_token(subject, expires_delta=timedelta(hours=1))
    payload = decode_access_token(token)
    assert payload["sub"] == subject
    assert "exp" in payload


def test_decode_access_token_garbage_returns_empty():
    result = decode_access_token("not.a.valid.token")
    assert result == {}
