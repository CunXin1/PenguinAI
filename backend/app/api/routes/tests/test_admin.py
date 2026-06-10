"""Tests for /api/admin endpoints (admin sub-package).

The admin API is mounted as a sub-package (see admin/router.py):
  GET  /api/admin/db/health          → database.db_health
  POST /api/admin/actions/{action}   → actions.trigger_action
Both require ADMIN tier.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.main import app
from app.models.user import User

_real_override = app.dependency_overrides.get(get_db)


@pytest.fixture(autouse=True)
def _restore_db_override():
    yield
    if _real_override is not None:
        app.dependency_overrides[get_db] = _real_override
    else:
        app.dependency_overrides.pop(get_db, None)


# ── Admin gating: non-admins get 403 (auth dependency rejects before any work) ──


async def test_db_health_non_admin_forbidden(
    client: AsyncClient, test_user: User, auth_headers
):
    resp = await client.get("/api/admin/db/health", headers=auth_headers(test_user))
    assert resp.status_code == 403


async def test_action_non_admin_forbidden(
    client: AsyncClient, test_user: User, auth_headers
):
    resp = await client.post(
        "/api/admin/actions/refresh-signals", headers=auth_headers(test_user)
    )
    assert resp.status_code == 403


# ── db/health (admin): mock the Postgres-only queries + pool so it runs on SQLite ──


async def test_db_health_admin_ok(
    client: AsyncClient, admin_user: User, auth_headers, db_session
):
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_result.mappings.return_value.all.return_value = []

    original_execute = db_session.execute

    async def _patched(stmt, *args, **kwargs):
        s = str(getattr(stmt, "text", stmt))
        # Stub the PG-specific introspection queries; let everything else
        # (notably the auth user lookup) hit the real SQLite session.
        if "pg_stat_activity" in s or "pg_class" in s or "pg_database_size" in s:
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    async def _override():
        db_session.execute = AsyncMock(side_effect=_patched)
        yield db_session

    mock_engine = MagicMock()
    mock_engine.pool.size.return_value = 5
    mock_engine.pool.checkedin.return_value = 5
    mock_engine.pool.checkedout.return_value = 0
    mock_engine.pool.overflow.return_value = 0
    mock_engine.pool._max_overflow = 10

    app.dependency_overrides[get_db] = _override
    with patch("app.api.routes.admin.database.engine", mock_engine):
        resp = await client.get("/api/admin/db/health", headers=auth_headers(admin_user))

    assert resp.status_code == 200
    data = resp.json()
    assert "connection_pool" in data
    assert "tables" in data
    assert "total_db_size_bytes" in data


# ── actions/{action} (admin): triggers the mapped Celery task ──────────────────


async def test_action_triggers_celery(
    client: AsyncClient, admin_user: User, auth_headers
):
    # actions.trigger_action does a lazy `from celery import Celery`, so patch the
    # source attribute on the celery module.
    with patch("celery.Celery") as MockCelery:
        mock_app = MagicMock()
        mock_app.send_task.return_value = MagicMock(id="task-123")
        MockCelery.return_value = mock_app

        resp = await client.post(
            "/api/admin/actions/refresh-signals", headers=auth_headers(admin_user)
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered"] is True
    assert body["task_name"] == "ml.tasks.hourly_signal_cache.refresh_top100"
    mock_app.send_task.assert_called_once_with(
        "ml.tasks.hourly_signal_cache.refresh_top100", queue="ml_inference"
    )


async def test_action_unknown_returns_404(
    client: AsyncClient, admin_user: User, auth_headers
):
    resp = await client.post(
        "/api/admin/actions/not-a-real-action", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 404
