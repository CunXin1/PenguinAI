"""
Daily pipeline tasks: model retraining, fundamentals fetch, Top-100 list update.
Runs at ~10pm ET after market close.
"""

import asyncio
import logging
from pathlib import Path

import redis

from ml.core.config import ml_settings
from ml.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
MODEL_DIR = Path("/models/penguinai")


@celery_app.task(name="ml.tasks.daily_pipeline.run_daily_pipeline", queue="ml_inference")
def run_daily_pipeline():
    """Full nightly pipeline: retrain models + update Top-100 list."""
    logger.info("Starting daily ML pipeline")
    asyncio.run(_async_daily_pipeline())


async def _async_daily_pipeline():
    from ml.models.rf_trainer import train as train_rf
    from ml.models.xgboost_trainer import train as train_xgb

    # Retrain XGBoost (reads the 30-min parquet under data/30min_data via DuckDB)
    try:
        metrics = train_xgb(output_path=MODEL_DIR / "xgboost_prod.pkl")
        logger.info("XGBoost retrained: %s", metrics)
    except Exception as e:
        logger.error("XGBoost training failed: %s", e)

    # Retrain RF
    try:
        metrics = train_rf(output_path=MODEL_DIR / "rf_prod.pkl")
        logger.info("RF retrained: %s", metrics)
    except Exception as e:
        logger.error("RF training failed: %s", e)

    # Hot-reload models in registry
    from ml.models.model_registry import model_registry

    model_registry.reload(MODEL_DIR)

    # Update Top-100 list in Redis
    await _update_top100_redis()


async def _update_top100_redis():
    """Rank tickers by recent signal confidence → store Top-100 in Redis."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(ml_settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        rows = await db.execute(
            text("""
                SELECT ticker FROM signal_cache
                ORDER BY confidence DESC
                LIMIT 100
            """)
        )
        top_tickers = [row[0] for row in rows.all()]

    r = redis.from_url(ml_settings.REDIS_URL)
    pipe = r.pipeline()
    pipe.delete(ml_settings.TOP100_TICKERS_KEY)
    if top_tickers:
        pipe.rpush(ml_settings.TOP100_TICKERS_KEY, *top_tickers)
    pipe.expire(ml_settings.TOP100_TICKERS_KEY, 86400)
    pipe.execute()

    logger.info("Top-100 Redis list updated with %d tickers", len(top_tickers))
    await engine.dispose()


@celery_app.task(name="ml.tasks.daily_pipeline.fetch_fundamentals", queue="default")
def fetch_fundamentals():
    """Stub: fetch PE ratios, earnings data from external API."""
    logger.info("Fetching fundamentals — implement with yfinance or Polygon.io")
