"""
Celery tasks for signal cache management.
- refresh_top100: runs every hour (market hours), pre-computes Top-100 signals
- compute_single_signal: on-demand for cold tickers
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import text

from ml.core.config import ml_settings
from ml.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_top100_tickers() -> list[str]:
    """Pull Top-100 ticker list from Redis (maintained by daily pipeline)."""
    r = redis.from_url(ml_settings.REDIS_URL)
    tickers = r.lrange(ml_settings.TOP100_TICKERS_KEY, 0, 99)
    return [t.decode() for t in tickers] if tickers else _hardcoded_top100()


def _hardcoded_top100() -> list[str]:
    """Fallback Top-100 while Redis is warming up."""
    return [
        "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "PLTR",
        "AMD", "ORCL", "NFLX", "CRM", "ADBE", "QCOM", "INTC", "MU", "MRVL",
        "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "GLD", "TLT",
        "BTC-USD", "ETH-USD",
        "JPM", "BAC", "GS", "MS", "V", "MA", "PYPL",
        "JNJ", "LLY", "PFE", "ABBV", "UNH",
        "XOM", "CVX", "COP",
        "COST", "WMT", "HD", "AMGN", "HON",
    ]


@celery_app.task(name="ml.tasks.hourly_signal_cache.refresh_top100", queue="ml_inference")
def refresh_top100():
    """Synchronous Celery task wrapper — runs async compute inside event loop."""
    asyncio.run(_async_refresh_top100())


async def _async_refresh_top100():
    from ml.inference.signal_engine import signal_engine
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    engine = create_async_engine(ml_settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tickers = _get_top100_tickers()
    logger.info("Refreshing signals for %d Top-100 tickers", len(tickers))

    # Each ticker gets its own session — async sessions must not be shared across coroutines
    BATCH_SIZE = 10
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        results = await asyncio.gather(
            *[_compute_and_save(ticker, SessionLocal, signal_engine) for ticker in batch],
            return_exceptions=True,
        )
        for ticker, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error("Failed signal for %s: %s", ticker, result)

    await engine.dispose()


async def _compute_and_save(ticker: str, SessionLocal, signal_engine) -> None:
    """Each ticker gets its own isolated session."""
    async with SessionLocal() as db:
        try:
            signal_data = await signal_engine.compute(ticker, db)
            signal_data["expires_at"] = datetime.now(timezone.utc) + timedelta(
                seconds=ml_settings.CACHE_TTL_TOP100
            )
            await _upsert_signal(db, signal_data)
            await db.commit()
            logger.debug("Cached %s: %s", ticker, signal_data["direction"])
        except Exception as e:
            await db.rollback()
            raise e


@celery_app.task(name="ml.tasks.hourly_signal_cache.compute_single_signal", queue="ml_inference")
def compute_single_signal(ticker: str):
    """On-demand signal computation for a cold (non-Top-100) ticker."""
    asyncio.run(_async_compute_single(ticker))


async def _async_compute_single(ticker: str):
    from ml.inference.signal_engine import signal_engine
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    engine = create_async_engine(ml_settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        try:
            signal_data = await signal_engine.compute(ticker, db)
            await _upsert_signal(db, signal_data)
            await db.commit()
            logger.info("On-demand signal computed for %s", ticker)
        except Exception as e:
            logger.error("On-demand signal failed for %s: %s", ticker, e)
            await db.rollback()

    await engine.dispose()


async def _upsert_signal(db, data: dict):
    """INSERT or UPDATE signal_cache row."""
    await db.execute(
        text("""
            INSERT INTO signal_cache
                (ticker, direction, confidence, holding_period,
                 xgb_prob_up, rf_prob_up, ensemble_prob,
                 finbert_score, post_count, hawk_dove_ref,
                 ai_attribution, ai_analysis, tier_required,
                 computed_at, expires_at)
            VALUES
                (:ticker, :direction, :confidence, :holding_period,
                 :xgb_prob_up, :rf_prob_up, :ensemble_prob,
                 :finbert_score, :post_count, :hawk_dove_ref,
                 :ai_attribution, :ai_analysis, :tier_required,
                 :computed_at, :expires_at)
            ON CONFLICT (ticker) DO UPDATE SET
                direction = EXCLUDED.direction,
                confidence = EXCLUDED.confidence,
                holding_period = EXCLUDED.holding_period,
                xgb_prob_up = EXCLUDED.xgb_prob_up,
                rf_prob_up = EXCLUDED.rf_prob_up,
                ensemble_prob = EXCLUDED.ensemble_prob,
                finbert_score = EXCLUDED.finbert_score,
                post_count = EXCLUDED.post_count,
                hawk_dove_ref = EXCLUDED.hawk_dove_ref,
                ai_attribution = EXCLUDED.ai_attribution,
                ai_analysis = EXCLUDED.ai_analysis,
                computed_at = EXCLUDED.computed_at,
                expires_at = EXCLUDED.expires_at
        """),
        data,
    )
