"""
Real-time data ingest tasks: IBKR 1-min stream and social media scraping.
"""

import asyncio
import logging

from ml.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ml.tasks.realtime_ingest.scrape_social_media", queue="default")
def scrape_social_media():
    """Trigger all social media scrapers and score with FinBERT."""
    asyncio.run(_async_scrape())


@celery_app.task(name="ml.tasks.realtime_ingest.fetch_earnings", queue="default")
def fetch_earnings(days_back: int = 7, days_ahead: int = 30):
    """Pull the Finnhub (free tier) earnings calendar into the earnings table.

    Delegates to data.ingestion.finnhub_earnings (idempotent upserts; re-runs
    fill in actuals as results publish). Scheduled by Celery Beat 3x/weekday
    (08:00 / 14:00 / 21:00 ET) to catch the forward calendar plus BMO (pre-open)
    and AMC (after-close) actuals. Logged no-op when FINNHUB_API_KEY is unset.
    """
    from data.ingestion.finnhub_earnings import run_default

    logger.info("Finnhub earnings fetch: -%dd .. +%dd", days_back, days_ahead)
    try:
        asyncio.run(run_default(days_back=days_back, days_ahead=days_ahead))
    except RuntimeError as exc:  # missing key / 401 / 429 — don't crash the beat
        logger.warning("earnings fetch skipped: %s", exc)


async def _async_scrape():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from data.scrapers.reddit_scraper import RedditScraper
    from data.scrapers.twitter_scraper import TwitterScraper
    from ml.core.config import ml_settings
    from ml.inference.finbert_scorer import finbert_scorer
    from ml.rag.embedder import embedder

    engine = create_async_engine(ml_settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    reddit = RedditScraper()
    twitter = TwitterScraper()

    new_posts = []
    new_posts.extend(await reddit.fetch_new_posts())
    new_posts.extend(await twitter.fetch_new_posts())

    if not new_posts:
        logger.info("No new social posts found")
        return

    logger.info("Scoring %d new posts with FinBERT", len(new_posts))
    texts = [p["content"] for p in new_posts]
    scores = finbert_scorer.score_batch(texts)
    embeddings = embedder.encode_batch(texts)

    async with SessionLocal() as db:
        for post, score, emb in zip(new_posts, scores, embeddings, strict=False):
            await db.execute(
                text("""
                    INSERT INTO social_posts
                        (time, ticker, platform, author, content, url,
                         finbert_score, finbert_label, embedding, is_vip)
                    VALUES
                        (:time, :ticker, :platform, :author, :content, :url,
                         :finbert_score, :finbert_label, :embedding, :is_vip)
                    ON CONFLICT DO NOTHING
                """),
                {
                    **post,
                    "finbert_score": score.sentiment,
                    "finbert_label": score.label,
                    "embedding": f"[{','.join(str(x) for x in emb.tolist())}]",
                },
            )
        await db.commit()

    await engine.dispose()
    logger.info("Saved %d posts to DB", len(new_posts))
