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

    Delegates to data.earnings.finnhub (idempotent upserts; re-runs fill in
    actuals as results publish). Normally managed by backend lifespan scheduler
    (startup + 2×/day); this Celery task remains available for manual invocation.
    """
    from data.earnings.finnhub import run_default

    logger.info("Finnhub earnings fetch: -%dd .. +%dd", days_back, days_ahead)
    try:
        asyncio.run(run_default(days_back=days_back, days_ahead=days_ahead))
    except RuntimeError as exc:  # missing key / 401 / 429 — don't crash the beat
        logger.warning("earnings fetch skipped: %s", exc)


@celery_app.task(name="ml.tasks.realtime_ingest.refresh_hot_news", queue="default")
def refresh_hot_news():
    """Fetch news for all hot tickers (Massive + Google merged) and store in DB.

    Kept for manual invocation only — news is normally ingested by the backend lifespan
    scheduler (``data.news.scheduler``), not Celery beat, so this is not scheduled.
    """
    from data.news.ingest import ingest_all

    try:
        count = asyncio.run(ingest_all())
        logger.info("Hot news refresh: %d new articles", count)
    except Exception as exc:
        logger.warning("Hot news refresh failed: %s", exc)


@celery_app.task(name="ml.tasks.realtime_ingest.fetch_congress_trades", queue="default")
def fetch_congress_trades():
    """Pull congressional stock transactions (House + Senate Stock Watcher)."""
    from data.celebrity.congress import run_default

    logger.info("Fetching congressional trades")
    try:
        asyncio.run(run_default())
    except RuntimeError as exc:
        logger.warning("congress trades fetch skipped: %s", exc)


@celery_app.task(name="ml.tasks.realtime_ingest.fetch_13f_filings", queue="default")
def fetch_13f_filings():
    """Pull latest 13F filings from SEC EDGAR for tracked institutional investors."""
    from data.celebrity.sec_13f import run_default

    logger.info("Fetching 13F filings")
    try:
        asyncio.run(run_default())
    except RuntimeError as exc:
        logger.warning("13F fetch skipped: %s", exc)


@celery_app.task(name="ml.tasks.realtime_ingest.fetch_ark_trades", queue="default")
def fetch_ark_trades():
    """Pull ARK Invest daily trade disclosures."""
    from data.celebrity.ark import run_default

    logger.info("Fetching ARK daily trades")
    try:
        asyncio.run(run_default())
    except RuntimeError as exc:
        logger.warning("ARK trades fetch skipped: %s", exc)


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
