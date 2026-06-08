"""Module 5: tests for /api/tickers and /api/symbols endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticker import Ticker
from app.models.user import User


@pytest.fixture
async def multiple_tickers(db_session: AsyncSession) -> list[Ticker]:
    tickers = [
        Ticker(
            ticker="AAPL",
            name="Apple Inc.",
            exchange="NASDAQ",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=3_000_000_000_000,
            is_active=True,
        ),
        Ticker(
            ticker="AAL",
            name="American Airlines Group",
            exchange="NASDAQ",
            sector="Industrials",
            industry="Airlines",
            market_cap=10_000_000_000,
            is_active=True,
        ),
        Ticker(
            ticker="MSFT",
            name="Microsoft Corporation",
            exchange="NASDAQ",
            sector="Technology",
            industry="Software",
            market_cap=2_800_000_000_000,
            is_active=True,
        ),
        Ticker(
            ticker="JNJ",
            name="Johnson & Johnson",
            exchange="NYSE",
            sector="Healthcare",
            industry="Pharmaceuticals",
            market_cap=400_000_000_000,
            is_active=True,
        ),
        Ticker(
            ticker="XOM",
            name="Exxon Mobil Corporation",
            exchange="NYSE",
            sector="Energy",
            industry="Oil & Gas",
            market_cap=450_000_000_000,
            is_active=True,
        ),
        Ticker(
            ticker="DELIST",
            name="Delisted Corp",
            exchange="NYSE",
            sector="Technology",
            industry="Software",
            market_cap=1_000_000,
            is_active=False,
        ),
    ]
    for t in tickers:
        t.tags = []
    db_session.add_all(tickers)
    await db_session.commit()
    return tickers


# ── Tickers: search ──────────────────────────────────────────────


async def test_search_prefix_match(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/search", params={"q": "AA"})
    assert resp.status_code == 200
    symbols = {t["ticker"] for t in resp.json()}
    assert "AAPL" in symbols
    assert "AAL" in symbols
    assert "MSFT" not in symbols


async def test_search_case_insensitive(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/search", params={"q": "aapl"})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert results[0]["ticker"] == "AAPL"


async def test_search_missing_q_returns_422(client: AsyncClient):
    resp = await client.get("/api/tickers/search")
    assert resp.status_code == 422


async def test_search_excludes_inactive(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/search", params={"q": "DELIST"})
    assert resp.status_code == 200
    symbols = {t["ticker"] for t in resp.json()}
    assert "DELIST" not in symbols


# ── Tickers: universe ────────────────────────────────────────────


async def test_universe_returns_list(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/universe")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    symbols = {t["ticker"] for t in data}
    assert "AAPL" in symbols
    assert "DELIST" not in symbols


async def test_universe_sector_filter(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/universe", params={"sector": "Technology"})
    assert resp.status_code == 200
    data = resp.json()
    sectors = {t["sector"] for t in data}
    assert sectors == {"Technology"}
    symbols = {t["ticker"] for t in data}
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    assert "JNJ" not in symbols


async def test_universe_pagination(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/universe", params={"offset": 0, "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# ── Tickers: single ──────────────────────────────────────────────


async def test_get_ticker_exists(client: AsyncClient, multiple_tickers: list[Ticker]):
    resp = await client.get("/api/tickers/AAPL")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"


async def test_get_ticker_not_found(client: AsyncClient):
    resp = await client.get("/api/tickers/ZZZZ")
    assert resp.status_code == 404


# ── Symbols: request (new symbol) ────────────────────────────────


async def test_request_new_symbol(client: AsyncClient):
    """POST /api/symbols/request for an uncovered symbol.

    The endpoint uses PostgreSQL-specific ``pg_insert().on_conflict_do_update``,
    which cannot run against the SQLite test DB.  We mock the db.execute that
    runs the upsert statement so the handler logic still executes.
    """
    mock_row = MagicMock()
    mock_row.status = "pending"
    mock_row.request_count = 1

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row

    original_execute = AsyncSession.execute

    async def _patched_execute(self, statement, *args, **kwargs):
        stmt_str = str(getattr(statement, "text", statement))
        if "symbol_requests" in stmt_str.lower() or "on conflict" in stmt_str.lower():
            return mock_result
        return await original_execute(self, statement, *args, **kwargs)

    with patch.object(AsyncSession, "execute", _patched_execute):
        resp = await client.post("/api/symbols/request", json={"symbol": "PLTR"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "PLTR"
    assert data["request_count"] == 1
    assert data["status"] == "pending"


async def test_request_already_covered_symbol(
    client: AsyncClient, multiple_tickers: list[Ticker]
):
    """POST /api/symbols/request for a covered ticker returns already_covered."""
    resp = await client.post("/api/symbols/request", json={"symbol": "AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_covered"
    assert data["request_count"] == 0


# ── Symbols: list requests (admin) ───────────────────────────────


async def test_list_symbol_requests_non_admin_forbidden(
    client: AsyncClient, test_user: User, auth_headers
):
    resp = await client.get(
        "/api/symbols/requests", headers=auth_headers(test_user)
    )
    assert resp.status_code == 403


async def test_list_symbol_requests_admin_ok(
    client: AsyncClient, admin_user: User, auth_headers
):
    resp = await client.get(
        "/api/symbols/requests", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
