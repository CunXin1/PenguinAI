from celery import Celery
from celery.schedules import crontab

from ml.core.config import ml_settings


celery_app = Celery(
    "penguinai",
    broker=ml_settings.REDIS_URL,
    backend=ml_settings.REDIS_URL,
    include=[
        "ml.tasks.hourly_signal_cache",
        "ml.tasks.daily_pipeline",
        "ml.tasks.realtime_ingest",
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
        "ml.tasks.daily_pipeline.*":      {"queue": "ml_inference"},
        "ml.tasks.realtime_ingest.*":     {"queue": "default"},
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
}
