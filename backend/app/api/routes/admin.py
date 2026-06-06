from typing import Annotated

from celery import Celery
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier
from app.core.config import settings

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))


@router.get("/pipeline/status")
async def pipeline_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    _=AdminUser,
):
    """Dashboard for monitoring data pipeline health."""
    row_counts = await db.execute(
        text("""
            SELECT
                (SELECT count(*) FROM bars_30m)           AS bars_30min,
                (SELECT count(*) FROM market_data_1min)   AS bars_1min,
                (SELECT count(*) FROM social_posts)       AS social_posts,
                (SELECT count(*) FROM signal_cache)       AS cached_signals
        """)
    )
    stats = row_counts.mappings().one()
    return {"db_stats": dict(stats)}


@router.post("/cache/refresh")
async def refresh_cache(_=AdminUser):
    """Manually trigger Top-100 signal cache refresh."""
    celery_app = Celery(broker=settings.REDIS_URL)
    celery_app.send_task("ml.tasks.hourly_signal_cache.refresh_top100", queue="ml_inference")
    return {"triggered": True}
