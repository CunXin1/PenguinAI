from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_tier
from app.core.config import settings

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))

_ACTIONS: dict[str, tuple[str, str]] = {
    "refresh-signals": (
        "ml.tasks.hourly_signal_cache.refresh_top100",
        "ml_inference",
    ),
    "retrain-models": (
        "ml.tasks.daily_pipeline.run_daily_pipeline",
        "ml_inference",
    ),
    "scrape-social": (
        "ml.tasks.realtime_ingest.scrape_social_media",
        "default",
    ),
    "fetch-earnings": (
        "ml.tasks.realtime_ingest.fetch_earnings",
        "default",
    ),
    "fetch-celebrities": (
        "ml.tasks.realtime_ingest.fetch_celebrity_holdings",
        "default",
    ),
    "fetch-news": (
        "ml.tasks.realtime_ingest.refresh_hot_news",
        "default",
    ),
    "validate-symbols": (
        "ml.tasks.symbol_validation.validate_symbol_requests",
        "default",
    ),
}


@router.post("/{action}")
async def trigger_action(action: str, _=AdminUser):
    """Manually trigger a Celery task."""
    if action not in _ACTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown action: {action}")

    task_name, queue = _ACTIONS[action]

    from celery import Celery

    cel = Celery(broker=settings.REDIS_URL)
    result = cel.send_task(task_name, queue=queue)

    return {
        "triggered": True,
        "task_id": result.id,
        "task_name": task_name,
    }


@router.get("/task/{task_id}")
async def task_result(task_id: str, _=AdminUser):
    """Check the status of a triggered Celery task."""
    from celery import Celery
    from celery.result import AsyncResult

    cel = Celery(broker=settings.REDIS_URL, backend=settings.REDIS_URL)
    result = AsyncResult(task_id, app=cel)

    return {
        "task_id": task_id,
        "status": result.status,
        "result": str(result.result)[:500] if result.result else None,
    }
