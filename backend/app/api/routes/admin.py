from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tier
from app.models.signal_cache import SignalCache

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))


@router.get("/pipeline/status")
async def pipeline_status(
    _=AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Dashboard for monitoring data pipeline health."""
    signal_count = await db.execute(select(func.count()).select_from(SignalCache))
    row_counts = await db.execute(
        text("""
            SELECT
                (SELECT count(*) FROM market_data_30min) AS bars_30min,
                (SELECT count(*) FROM market_data_1min)  AS bars_1min,
                (SELECT count(*) FROM social_posts)       AS social_posts,
                (SELECT count(*) FROM signal_cache)       AS cached_signals
        """)
    )
    stats = row_counts.mappings().one()
    return {"db_stats": dict(stats)}


@router.post("/cache/refresh")
async def refresh_cache(_=AdminUser):
    """Manually trigger Top-100 signal cache refresh."""
    from ml.tasks.celery_app import celery_app
    celery_app.send_task("ml.tasks.hourly_signal_cache.refresh_top100", queue="ml_inference")
    return {"triggered": True}
