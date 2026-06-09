from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_tier
from app.core.config import settings

router = APIRouter()
AdminUser = Depends(require_tier("ADMIN"))

_BEAT_SCHEDULE = [
    {
        "name": "refresh-top100-signals",
        "task": "ml.tasks.hourly_signal_cache.refresh_top100",
        "schedule": "hourly 9–17 ET weekdays",
    },
    {
        "name": "daily-model-pipeline",
        "task": "ml.tasks.daily_pipeline.run_daily_pipeline",
        "schedule": "10pm ET weekdays",
    },
    {
        "name": "scrape-social",
        "task": "ml.tasks.realtime_ingest.scrape_social_media",
        "schedule": "every 30 min",
    },
    {
        "name": "fetch-fundamentals",
        "task": "ml.tasks.daily_pipeline.fetch_fundamentals",
        "schedule": "8am ET weekdays",
    },
    {
        "name": "refresh-hot-news",
        "task": "ml.tasks.realtime_ingest.refresh_hot_news",
        "schedule": "every 30 min (:15/:45)",
    },
    {
        "name": "validate-symbol-requests",
        "task": "ml.tasks.symbol_validation.validate_symbol_requests",
        "schedule": "every 6h (:30)",
    },
]


@router.get("/status")
async def task_status(_=AdminUser):
    """Celery task history, queue depths, and worker info."""
    import redis as sync_redis
    from celery import Celery

    r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=2)

    # 1. Scheduled task last-run info from Redis hash
    scheduled_tasks = []
    for entry in _BEAT_SCHEDULE:
        raw = r.hget("admin:task_runs", entry["task"])
        run_info: dict = json.loads(raw) if raw else {}
        scheduled_tasks.append(
            {
                "name": entry["name"],
                "task": entry["task"],
                "schedule": entry["schedule"],
                "last_run": run_info.get("started_at"),
                "last_status": run_info.get("status"),
                "last_duration_s": run_info.get("duration_s"),
            }
        )

    # 2. Queue depths (Celery with Redis broker stores queues as Redis lists)
    queues = []
    for q_name in ("default", "ml_inference"):
        pending = r.llen(q_name) or 0
        queues.append({"name": q_name, "pending": pending})

    # 3. Worker info via Celery inspect
    workers = []
    try:
        cel = Celery(broker=settings.REDIS_URL)
        inspector = cel.control.inspect(timeout=2.0)
        ping_resp = inspector.ping() or {}
        active_resp = inspector.active() or {}
        stats_resp = inspector.stats() or {}

        for worker_name in ping_resp:
            stats = stats_resp.get(worker_name, {})
            active = active_resp.get(worker_name, [])
            pool_info = stats.get("pool", {})
            worker_queues = [
                q.get("name", "?")
                for q in (stats.get("consumer", {}).get("queues", []) or [])
            ]
            workers.append(
                {
                    "name": worker_name,
                    "status": "online",
                    "active_tasks": len(active),
                    "processed": stats.get("total", {}).get(
                        "ml.tasks.hourly_signal_cache.refresh_top100", 0
                    )
                    if not stats.get("total")
                    else sum(stats.get("total", {}).values()),
                    "concurrency": pool_info.get("max-concurrency", 0),
                    "queues": worker_queues,
                }
            )
    except Exception:
        pass

    r.close()
    return {
        "scheduled_tasks": scheduled_tasks,
        "queues": queues,
        "workers": workers,
    }
