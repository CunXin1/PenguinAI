import json
from datetime import UTC, datetime

import redis
from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_prerun, task_success

from ml.core.config import ml_settings

celery_app = Celery(
    "penguinai",
    broker=ml_settings.REDIS_URL,
    backend=ml_settings.REDIS_URL,
    include=[
        "ml.tasks.hourly_signal_cache",
        "ml.tasks.daily_pipeline",
        "ml.tasks.realtime_ingest",
        "ml.tasks.symbol_validation",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="US/Eastern",
    enable_utc=True,
    task_routes={
        "ml.tasks.hourly_signal_cache.*": {"queue": "ml_inference"},
        "ml.tasks.daily_pipeline.*": {"queue": "ml_inference"},
        "ml.tasks.realtime_ingest.*": {"queue": "default"},
        "ml.tasks.symbol_validation.*": {"queue": "default"},
    },
)

# ── Scheduled tasks ───────────────────────────────────────────────────────────
celery_app.conf.beat_schedule = {
    # Top-100 cache refresh every hour during market hours (9am–5pm ET weekdays)
    "refresh-top100-signals": {
        "task": "ml.tasks.hourly_signal_cache.refresh_top100",
        "schedule": crontab(minute=0, hour="9-17", day_of_week="1-5"),
    },
    # Daily model pipeline at 10pm ET (after market close + data settle)
    "daily-model-pipeline": {
        "task": "ml.tasks.daily_pipeline.run_daily_pipeline",
        "schedule": crontab(minute=0, hour=22, day_of_week="1-5"),
    },
    # Scrape social media every 30 minutes
    "scrape-social": {
        "task": "ml.tasks.realtime_ingest.scrape_social_media",
        "schedule": crontab(minute="*/30"),
    },
    # Fetch FOMC and fundamentals daily at 8am ET
    "fetch-fundamentals": {
        "task": "ml.tasks.daily_pipeline.fetch_fundamentals",
        "schedule": crontab(minute=0, hour=8, day_of_week="1-5"),
    },
    # Earnings: managed by backend lifespan (fetch on startup + 2× daily 08:00/18:00 ET).
    # Celery task remains available for manual invocation but is not scheduled here.
    # Hot ticker news every 30 minutes (:15 and :45 to avoid collision with other tasks)
    "refresh-hot-news": {
        "task": "ml.tasks.realtime_ingest.refresh_hot_news",
        "schedule": crontab(minute="15,45"),
    },
    # Classify user-requested (uncovered) symbols via Massive every 6 hours.
    "validate-symbol-requests": {
        "task": "ml.tasks.symbol_validation.validate_symbol_requests",
        "schedule": crontab(minute=30, hour="*/6"),
    },
    # Celebrity holdings: managed by backend lifespan (fetch on startup + daily 19:00 ET).
    # Celery tasks remain available for manual invocation but are not scheduled here.
}


# ── Admin task tracking (writes execution metadata to Redis) ─────────────────

_REDIS_HASH = "admin:task_runs"


def _redis():
    return redis.from_url(ml_settings.REDIS_URL, decode_responses=True, socket_timeout=2)


@task_prerun.connect
def _on_task_prerun(sender=None, task_id=None, **kwargs):
    try:
        r = _redis()
        r.hset(
            _REDIS_HASH,
            sender.name,
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "RUNNING",
                    "started_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
        r.close()
    except Exception:
        pass


@task_success.connect
def _on_task_success(sender=None, **kwargs):
    try:
        r = _redis()
        raw = r.hget(_REDIS_HASH, sender.name)
        info = json.loads(raw) if raw else {}
        started = info.get("started_at")
        duration = None
        if started:
            started_dt = datetime.fromisoformat(started)
            duration = round((datetime.now(UTC) - started_dt).total_seconds(), 2)
        info.update(
            {
                "status": "SUCCESS",
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_s": duration,
            }
        )
        r.hset(_REDIS_HASH, sender.name, json.dumps(info))
        r.close()
    except Exception:
        pass


@task_failure.connect
def _on_task_failure(sender=None, exception=None, **kwargs):
    try:
        r = _redis()
        raw = r.hget(_REDIS_HASH, sender.name)
        info = json.loads(raw) if raw else {}
        started = info.get("started_at")
        duration = None
        if started:
            started_dt = datetime.fromisoformat(started)
            duration = round((datetime.now(UTC) - started_dt).total_seconds(), 2)
        info.update(
            {
                "status": "FAILURE",
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_s": duration,
                "error": str(exception)[:200] if exception else None,
            }
        )
        r.hset(_REDIS_HASH, sender.name, json.dumps(info))
        r.close()
    except Exception:
        pass
