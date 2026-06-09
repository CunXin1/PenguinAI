"""Module 6a: tests for /api/admin endpoints."""

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


async def test_pipeline_status_non_admin_forbidden(
    client: AsyncClient, test_user: User, auth_headers
):
    resp = await client.get("/api/admin/pipeline/status", headers=auth_headers(test_user))
    assert resp.status_code == 403


async def test_pipeline_status_admin_ok(
    client: AsyncClient, admin_user: User, auth_headers, db_session
):
    mock_row = {"bars_30min": 100, "bars_1min": 50, "social_posts": 10, "cached_signals": 5}
    mock_result = MagicMock()
    mock_result.mappings.return_value.one.return_value = mock_row

    original_execute = db_session.execute

    async def _patched(stmt, *args, **kwargs):
        stmt_str = str(getattr(stmt, "text", stmt))
        if "bars_30m" in stmt_str or "signal_cache" in stmt_str:
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    async def _override():
        db_session.execute = AsyncMock(side_effect=_patched)
        yield db_session

    app.dependency_overrides[get_db] = _override

    resp = await client.get("/api/admin/pipeline/status", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert "db_stats" in data


async def test_cache_refresh_non_admin_forbidden(
    client: AsyncClient, test_user: User, auth_headers
):
    resp = await client.post("/api/admin/cache/refresh", headers=auth_headers(test_user))
    assert resp.status_code == 403


async def test_cache_refresh_admin_triggers_celery(
    client: AsyncClient, admin_user: User, auth_headers
):
    with patch("app.api.routes.admin.Celery") as MockCelery:
        mock_app = MagicMock()
        MockCelery.return_value = mock_app

        resp = await client.post("/api/admin/cache/refresh", headers=auth_headers(admin_user))

    assert resp.status_code == 200
    assert resp.json() == {"triggered": True}
    mock_app.send_task.assert_called_once_with(
        "ml.tasks.hourly_signal_cache.refresh_top100", queue="ml_inference"
    )
