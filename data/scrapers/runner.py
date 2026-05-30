"""
Scraper runner — long-lived process that dispatches Celery scrape tasks
on a schedule. Runs in its own Docker container (no GPU needed).
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scraper.runner")

# Scrape intervals (seconds)
SOCIAL_INTERVAL = 30 * 60    # 30 minutes
FOMC_INTERVAL   = 6 * 3600   # 6 hours
SEC_INTERVAL     = 24 * 3600  # 24 hours

_running = True


def _handle_shutdown(sig, frame):
    global _running
    logger.info("Shutdown signal received, stopping scraper runner...")
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


async def _dispatch_social():
    """Send scrape task to Celery instead of running inline — keeps this process light."""
    from celery import Celery
    from ml.core.config import ml_settings
    app = Celery(broker=ml_settings.REDIS_URL)
    app.send_task("ml.tasks.realtime_ingest.scrape_social_media", queue="default")
    logger.info("Dispatched scrape_social_media task")


async def _dispatch_fomc():
    from data.scrapers.sec_scraper import sec_scraper
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import text
    from ml.core.config import ml_settings

    result = await sec_scraper.fetch_fomc_statement()
    if not result:
        return

    engine = create_async_engine(ml_settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO fomc_statements (time, document_url, hawk_dove_score, summary, raw_text)
                VALUES (:time, :document_url, :hawk_dove_score, :summary, :raw_text)
                ON CONFLICT (document_url) DO NOTHING
            """),
            result,
        )
        await db.commit()
    await engine.dispose()
    logger.info("FOMC statement saved, hawk_dove=%.3f", result["hawk_dove_score"])


async def run():
    logger.info("Scraper runner started")

    last_social = 0.0
    last_fomc   = 0.0

    while _running:
        now = datetime.now().timestamp()

        if now - last_social >= SOCIAL_INTERVAL:
            try:
                await _dispatch_social()
            except Exception as e:
                logger.error("Social dispatch failed: %s", e)
            last_social = now

        if now - last_fomc >= FOMC_INTERVAL:
            try:
                await _dispatch_fomc()
            except Exception as e:
                logger.error("FOMC fetch failed: %s", e)
            last_fomc = now

        await asyncio.sleep(60)   # check every minute

    logger.info("Scraper runner stopped")


if __name__ == "__main__":
    asyncio.run(run())
