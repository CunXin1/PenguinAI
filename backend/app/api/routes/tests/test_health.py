"""Tests for the layered health probes added for deploy hardening."""

from unittest.mock import MagicMock, patch

from httpx import AsyncClient


async def test_health_live(client: AsyncClient):
    """Liveness has no dependencies — always 200 while the process is up."""
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


async def test_health_ready_ok(client: AsyncClient):
    """SQLite SELECT 1 succeeds → ready (Redis is a soft dep, any state is fine)."""
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert "redis" in body["checks"]


async def test_health_ready_db_down_returns_503(client: AsyncClient):
    """If the DB probe fails, readiness must report 503 so orchestrators divert traffic."""
    import app.core.database as db

    broken = MagicMock()
    broken.connect.side_effect = RuntimeError("db down")
    with patch.object(db, "engine", broken):
        resp = await client.get("/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"].startswith("error")
