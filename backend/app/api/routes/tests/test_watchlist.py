"""Tests for /api/watchlist routes.

Watchlist is standard ORM CRUD (no raw SQL), so it works against the SQLite
test DB provided by the shared conftest fixtures.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.signal_cache import SignalCache
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def extra_ticker(db_session):
    """Insert a second ticker (MSFT) for multi-item tests."""
    t = Ticker(ticker="MSFT", name="Microsoft Corp", is_active=True)
    db_session.add(t)
    await db_session.flush()
    return t


async def _add_watchlist_row(db_session, user, ticker_str: str):
    db_session.add(Watchlist(user_id=user.id, ticker=ticker_str))
    await db_session.flush()


# ---------------------------------------------------------------------------
# GET /api/watchlist — auth gating
# ---------------------------------------------------------------------------

async def test_get_watchlist_unauthenticated_returns_401(client):
    resp = await client.get("/api/watchlist")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/watchlist — empty
# ---------------------------------------------------------------------------

async def test_get_watchlist_empty(client, test_user, auth_headers):
    headers = auth_headers(test_user)
    resp = await client.get("/api/watchlist", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/watchlist/{ticker} — add valid
# ---------------------------------------------------------------------------

async def test_add_ticker_to_watchlist(client, test_user, auth_headers, test_ticker):
    headers = auth_headers(test_user)
    resp = await client.post("/api/watchlist/aapl", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert body["added"] is True


# ---------------------------------------------------------------------------
# POST /api/watchlist/{ticker} — duplicate
# ---------------------------------------------------------------------------

async def test_add_duplicate_ticker_returns_409(
    client, test_user, auth_headers, test_ticker, db_session
):
    await _add_watchlist_row(db_session, test_user, "AAPL")
    headers = auth_headers(test_user)
    resp = await client.post("/api/watchlist/AAPL", headers=headers)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/watchlist/{ticker} — nonexistent ticker
# ---------------------------------------------------------------------------

async def test_add_nonexistent_ticker_returns_404(client, test_user, auth_headers):
    headers = auth_headers(test_user)
    resp = await client.post("/api/watchlist/ZZZZ", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/watchlist/{ticker} — exists
# ---------------------------------------------------------------------------

async def test_delete_ticker_from_watchlist(
    client, test_user, auth_headers, test_ticker, db_session
):
    await _add_watchlist_row(db_session, test_user, "AAPL")
    headers = auth_headers(test_user)
    resp = await client.delete("/api/watchlist/AAPL", headers=headers)
    assert resp.status_code == 204

    row = await db_session.execute(
        select(Watchlist).where(
            Watchlist.user_id == test_user.id, Watchlist.ticker == "AAPL"
        )
    )
    assert row.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# DELETE /api/watchlist/{ticker} — doesn't exist (graceful)
# ---------------------------------------------------------------------------

async def test_delete_nonexistent_ticker_is_graceful(
    client, test_user, auth_headers, test_ticker
):
    headers = auth_headers(test_user)
    resp = await client.delete("/api/watchlist/AAPL", headers=headers)
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# GET /api/watchlist — returns items with signal field
# ---------------------------------------------------------------------------

async def test_get_watchlist_returns_items_with_signal(
    client, test_user, auth_headers, test_ticker, test_signal, db_session
):
    await _add_watchlist_row(db_session, test_user, "AAPL")
    headers = auth_headers(test_user)
    resp = await client.get("/api/watchlist", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["ticker"] == "AAPL"
    assert item["signal"] is not None
    assert "direction" in item["signal"]
    assert "confidence" in item["signal"]
