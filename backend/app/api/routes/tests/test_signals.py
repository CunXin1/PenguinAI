"""Tests for GET /api/signals/top and GET /api/signals/{ticker}."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal_cache import SignalCache
from app.models.ticker import Ticker
from app.models.user import User


async def test_top_signals_anonymous(client: AsyncClient, test_signal: SignalCache):
    resp = await client.get("/api/signals/top")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["ticker"] == "AAPL"


async def test_top_signals_respects_limit(
    client: AsyncClient, db_session: AsyncSession, test_ticker: Ticker
):
    now = datetime.now(UTC)
    for i in range(10):
        sig = SignalCache(
            ticker=f"T{i:03d}",
            direction="LONG",
            confidence=Decimal("0.5000"),
            holding_period="INTRADAY",
            tier_required="FREE",
            computed_at=now,
            expires_at=now + timedelta(hours=1),
        )
        # Also need a ticker row for each (universe gate is only on /{ticker},
        # but /top just queries signal_cache so we only need the signal rows).
        db_session.add(sig)
    await db_session.commit()

    resp = await client.get("/api/signals/top?limit=5")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


async def test_get_signal_cache_hit(client: AsyncClient, test_signal: SignalCache):
    resp = await client.get("/api/signals/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["direction"] == "LONG"
    assert "ml_scores" in data


@patch("app.api.routes.signals._trigger_signal_computation")
async def test_get_signal_cache_miss_triggers_celery(
    mock_trigger: MagicMock,
    client: AsyncClient,
    test_ticker: Ticker,
):
    resp = await client.get("/api/signals/AAPL")
    assert resp.status_code == 202
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert "retry_after" in data
    mock_trigger.assert_called_once_with("AAPL")


@patch("app.api.routes.signals._trigger_signal_computation")
async def test_get_signal_poll_no_celery_retrigger(
    mock_trigger: MagicMock,
    client: AsyncClient,
    test_ticker: Ticker,
):
    resp = await client.get("/api/signals/AAPL?poll=true")
    assert resp.status_code == 202
    mock_trigger.assert_not_called()


async def test_get_signal_not_in_universe(client: AsyncClient):
    resp = await client.get("/api/signals/ZZZZZZ")
    assert resp.status_code == 404
    data = resp.json()
    assert data["reason"] == "not_in_universe"


async def test_get_signal_delisted(client: AsyncClient, db_session: AsyncSession):
    ticker = Ticker(
        ticker="DEAD",
        name="Dead Corp",
        tags=None,
        is_active=False,
    )
    db_session.add(ticker)
    await db_session.commit()

    resp = await client.get("/api/signals/DEAD")
    assert resp.status_code == 404
    data = resp.json()
    assert data["reason"] == "delisted"


async def test_tier_gating_free_blocked(
    client: AsyncClient,
    db_session: AsyncSession,
    test_ticker: Ticker,
    test_user: User,
    auth_headers,
):
    now = datetime.now(UTC)
    signal = SignalCache(
        ticker="AAPL",
        direction="LONG",
        confidence=Decimal("0.9000"),
        holding_period="SWING",
        tier_required="PRO",
        computed_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(signal)
    await db_session.commit()

    resp = await client.get("/api/signals/AAPL", headers=auth_headers(test_user))
    assert resp.status_code == 403


async def test_tier_gating_pro_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
    test_ticker: Ticker,
    pro_user: User,
    auth_headers,
):
    now = datetime.now(UTC)
    signal = SignalCache(
        ticker="AAPL",
        direction="SHORT",
        confidence=Decimal("0.7500"),
        holding_period="INTRADAY",
        tier_required="PRO",
        computed_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(signal)
    await db_session.commit()

    resp = await client.get("/api/signals/AAPL", headers=auth_headers(pro_user))
    assert resp.status_code == 200
    assert resp.json()["direction"] == "SHORT"


async def test_admin_bypasses_tier(
    client: AsyncClient,
    db_session: AsyncSession,
    test_ticker: Ticker,
    admin_user: User,
    auth_headers,
):
    now = datetime.now(UTC)
    signal = SignalCache(
        ticker="AAPL",
        direction="NEUTRAL",
        confidence=Decimal("0.6000"),
        holding_period="POSITION",
        tier_required="PREMIUM",
        computed_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(signal)
    await db_session.commit()

    resp = await client.get("/api/signals/AAPL", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["direction"] == "NEUTRAL"
