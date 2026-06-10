"""Tests for Settings validation — the production SECRET_KEY fail-fast guard."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_insecure_secret_key_rejected_in_production():
    """A default/known key with DEBUG=false must refuse to start."""
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="change_me", DEBUG=False)


def test_empty_secret_key_rejected_in_production():
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="", DEBUG=False)


def test_strong_secret_key_accepted_in_production():
    s = Settings(SECRET_KEY="a-sufficiently-long-and-unique-secret-value", DEBUG=False)
    assert s.SECRET_KEY == "a-sufficiently-long-and-unique-secret-value"


def test_insecure_secret_key_tolerated_in_debug():
    """In DEBUG an ephemeral random key is minted instead of failing."""
    s = Settings(SECRET_KEY="change_me", DEBUG=True)
    assert s.SECRET_KEY not in ("change_me", "")
    assert len(s.SECRET_KEY) >= 32
