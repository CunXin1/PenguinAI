"""Tests for /api/market-data routes.

Market-data routes hit TimescaleDB-specific SQL (time_bucket, DISTINCT ON, LATERAL),
which SQLite cannot execute. We override get_db to yield a mock session so the
tests verify HTTP wiring, parameter handling, and response shaping.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import get_db
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MappingRow:
    """Dict-like object that supports dict(row) conversion, matching SA RowMapping."""
    def __init__(self, d: dict):
        self._d = d
    def __getitem__(self, key):
        return self._d[key]
    def get(self, key, default=None):
        return self._d.get(key, default)
    def keys(self):
        return self._d.keys()
    def __iter__(self):
        return iter(self._d)
    def __len__(self):
        return len(self._d)


def _result_with_mappings(rows: list[dict]):
    result = MagicMock()
    result.mappings.return_value = [_MappingRow(r) for r in rows]
    return result


def _mock_db_override(execute_side_effect):
    """Create a get_db override that returns a mock session with given execute behavior."""
    async def _override():
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=execute_side_effect)
        yield session
    return _override


def _mock_db_override_single(result):
    """Create a get_db override that returns a mock session with a single execute return."""
    async def _override():
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        yield session
    return _override


# ---------------------------------------------------------------------------
# Restore the real get_db override after each mocked test
# ---------------------------------------------------------------------------

_real_override = app.dependency_overrides.get(get_db)


@pytest.fixture(autouse=True)
def _restore_db_override():
    yield
    if _real_override is not None:
        app.dependency_overrides[get_db] = _real_override
    else:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /api/market-data/status
# ---------------------------------------------------------------------------

@patch("app.api.routes.market_data.get_market_status")
async def test_market_status_returns_expected_keys(mock_get_status, client):
    mock_get_status.return_value = {
        "market_open": True,
        "session_open": True,
        "source": "session",
        "as_of": datetime.now(UTC).isoformat(),
        "latest_tick": datetime.now(UTC).isoformat(),
    }
    resp = await client.get("/api/market-data/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "market_open" in body
    assert "source" in body
    assert body["market_open"] is True


# ---------------------------------------------------------------------------
# GET /api/market-data/{ticker}/candles
# ---------------------------------------------------------------------------

async def test_candles_returns_list_of_bars(client):
    now = datetime.now(UTC)
    fake_rows = [
        {"time": now - timedelta(hours=2), "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0, "volume": 10000},
        {"time": now - timedelta(hours=1), "open": 151.0, "high": 153.0, "low": 150.0, "close": 152.5, "volume": 12000},
    ]
    app.dependency_overrides[get_db] = _mock_db_override_single(_result_with_mappings(fake_rows))

    resp = await client.get("/api/market-data/aapl/candles?timeframe=30min&days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert body["timeframe"] == "30min"
    assert len(body["candles"]) == 2
    candle = body["candles"][0]
    for key in ("time", "open", "high", "low", "close", "volume"):
        assert key in candle


async def test_candles_uppercases_ticker(client):
    app.dependency_overrides[get_db] = _mock_db_override_single(_result_with_mappings([]))
    resp = await client.get("/api/market-data/msft/candles")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "MSFT"


# ---------------------------------------------------------------------------
# GET /api/market-data/quotes
# ---------------------------------------------------------------------------

async def test_quotes_empty_tickers_returns_empty(client):
    resp = await client.get("/api/market-data/quotes?tickers=")
    assert resp.status_code == 200
    assert resp.json()["quotes"] == []


async def test_quotes_returns_records(client):
    now = datetime.now(UTC)
    fake_rows = [
        {"ticker": "SPY", "price": 450.0, "base": 448.0, "time": now},
        {"ticker": "QQQ", "price": 380.0, "base": None, "time": now},
    ]
    app.dependency_overrides[get_db] = _mock_db_override_single(_result_with_mappings(fake_rows))
    resp = await client.get("/api/market-data/quotes?tickers=SPY,QQQ")
    assert resp.status_code == 200
    quotes = resp.json()["quotes"]
    assert len(quotes) == 2
    for q in quotes:
        assert "ticker" in q
        assert "price" in q
        assert "change_pct" in q


# ---------------------------------------------------------------------------
# GET /api/market-data/mini
# ---------------------------------------------------------------------------

async def test_mini_empty_tickers_returns_empty(client):
    resp = await client.get("/api/market-data/mini?tickers=")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# GET /api/market-data/{ticker}/series
# ---------------------------------------------------------------------------

async def test_series_invalid_range_returns_422(client):
    resp = await client.get("/api/market-data/AAPL/series?range=6H")
    assert resp.status_code == 422
    assert "range must be one of" in resp.json()["detail"]


async def test_series_valid_range_returns_bars(client):
    now = datetime.now(UTC)
    fake_rows = [
        {"t": now - timedelta(hours=3), "o": 140.0, "h": 142.0, "l": 139.0, "c": 141.0, "v": 5000},
    ]
    app.dependency_overrides[get_db] = _mock_db_override_single(_result_with_mappings(fake_rows))
    resp = await client.get("/api/market-data/AAPL/series?range=1W")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert body["range"] == "1W"
    assert len(body["bars"]) == 1
    bar = body["bars"][0]
    assert "time" in bar
    for key in ("open", "high", "low", "close", "volume"):
        assert key in bar


# ---------------------------------------------------------------------------
# GET /api/market-data/heatmap
# ---------------------------------------------------------------------------

async def test_heatmap_returns_tiles_and_indices(client):
    now = datetime.now(UTC)
    map_rows = [
        {
            "ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology",
            "market_cap": 3_000_000_000_000,
            "last_close": 190.0, "prev_close": 188.0,
            "ret_5d": 0.01, "ret_21d": 0.03, "ret_63d": 0.05, "ret_252d": 0.15,
        },
    ]
    idx_rows = [
        {
            "symbol": "SPY", "last_close": 450.0, "prev_close": 448.0,
            "ret_5d": 0.005, "ret_21d": 0.02, "ret_63d": 0.04, "ret_252d": 0.12,
        },
    ]

    call_count = 0

    async def _fake_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # SELECT max(time) FROM market_data_1min → .scalar()
            scalar_result = MagicMock()
            scalar_result.scalar.return_value = None
            return scalar_result
        if call_count == 2:
            return _result_with_mappings(map_rows)
        if call_count == 3:
            return _result_with_mappings(idx_rows)
        return _result_with_mappings([])

    app.dependency_overrides[get_db] = _mock_db_override(_fake_execute)

    with (
        patch("app.api.routes.market_data.is_regular_session", return_value=False),
        patch("app.api.routes.market_data.ticks_advancing", return_value=False),
    ):
        resp = await client.get("/api/market-data/heatmap?limit=10&period=1D")

    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "indices" in body
    assert body["market_open"] is False
    assert body["period"] == "1D"
