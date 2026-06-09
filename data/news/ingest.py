"""Fetch hot-ticker news from Massive API and store in the news_articles table.

Two tiers:
  - **Hot tickers** (Nasdaq-100 top components + key ETFs): periodically fetched
    by Celery Beat, stored in DB with sentiment, consumed by ML pipeline.
  - **Cold tickers**: fetched on-demand by the API route, NOT stored.

This module handles the hot tier.  A lightweight Google News RSS fallback
(``fetch_google_news_rss``) provides zero-cost general market headlines.

RUN (repo root; needs MASSIVE_API_KEY in .env):
    python -m data.news.ingest           # one-shot
    python -m data.news.ingest --dry-run  # print only
"""

import argparse
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.ingestion.massive_reference import _get_json, _RateLimiter, _with_key, settings
from data.news.constants import HOT_TICKERS_LIST as HOT_TICKERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("news_ingest")

_RATE_PER_SEC = 5.0  # polite cap — well under Massive limits
_BATCH_SIZE = 10  # tickers per request (comma-separated)

# ── Sentiment mapping ────────────────────────────────────────────────────────
_SENTIMENT_SCORE: dict[str, float] = {
    "positive": 0.5,
    "negative": -0.5,
    "neutral": 0.0,
}


def _parse_published(raw: str) -> datetime:
    """Parse RFC 3339 timestamp from Massive, with fallback for common variants."""
    # Massive returns ISO 8601 / RFC 3339 strings like "2024-06-01T12:00:00Z"
    raw = raw.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _extract_sentiment(article: dict, ticker: str) -> tuple[str | None, float | None, str | None]:
    """Find the first insight matching *ticker* and return (label, score, reasoning)."""
    for insight in article.get("insights") or []:
        if insight.get("ticker", "").upper() == ticker.upper():
            label = (insight.get("sentiment") or "").lower()
            return label or None, _SENTIMENT_SCORE.get(label), insight.get("sentiment_reasoning")
    # fallback: first insight regardless of ticker
    for insight in article.get("insights") or []:
        label = (insight.get("sentiment") or "").lower()
        if label:
            return label, _SENTIMENT_SCORE.get(label), insight.get("sentiment_reasoning")
    return None, None, None


def _map_article(article: dict, query_ticker: str) -> dict:
    """Map a Massive news article to our news_articles row dict."""
    source_id = str(article["id"])
    sentiment, sentiment_score, sentiment_reasoning = _extract_sentiment(article, query_ticker)

    publisher = article.get("publisher") or {}
    return {
        "id": f"massive:{source_id}",
        "source_provider": "massive",
        "source_id": source_id,
        "headline": article.get("title") or "",
        "summary": article.get("description") or "",
        "article_url": article.get("article_url") or "",
        "image_url": article.get("image_url") or "",
        "author": article.get("author") or "",
        "publisher_name": publisher.get("name") or "",
        "published_at": _parse_published(article["published_utc"]),
        "tickers": article.get("tickers") or [],
        "category": "general",
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "sentiment_reasoning": sentiment_reasoning,
        "is_hot": True,
    }


_UPSERT_SQL = text("""
    INSERT INTO news_articles
        (id, source_provider, source_id, headline, summary, article_url,
         image_url, author, publisher_name, published_at, tickers,
         category, sentiment, sentiment_score, sentiment_reasoning, is_hot, fetched_at)
    VALUES
        (:id, :source_provider, :source_id, :headline, :summary, :article_url,
         :image_url, :author, :publisher_name, :published_at, :tickers,
         :category, :sentiment, :sentiment_score, :sentiment_reasoning, :is_hot, NOW())
    ON CONFLICT (id) DO UPDATE SET
        sentiment        = EXCLUDED.sentiment,
        sentiment_score  = EXCLUDED.sentiment_score,
        sentiment_reasoning = EXCLUDED.sentiment_reasoning,
        fetched_at       = NOW()
""")


async def fetch_hot_news() -> int:
    """Fetch news for hot tickers from Massive, store in news_articles table.

    Returns count of new articles inserted (or updated).
    """
    if not settings.MASSIVE_API_KEY:
        logger.error("MASSIVE_API_KEY is empty — set it in .env")
        return 0

    base = settings.MASSIVE_BASE_URL.rstrip("/")
    key = settings.MASSIVE_API_KEY
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    limiter = _RateLimiter(_RATE_PER_SEC)
    all_rows: dict[str, dict] = {}  # keyed by article id to deduplicate

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        # Process tickers in batches (comma-separated in the query param)
        for i in range(0, len(HOT_TICKERS), _BATCH_SIZE):
            batch = HOT_TICKERS[i : i + _BATCH_SIZE]
            ticker_param = ",".join(batch)
            url = _with_key(
                f"{base}/v2/reference/news?ticker={ticker_param}&limit=50", key
            )
            try:
                data = await _get_json(client, url, limiter)
            except Exception as exc:
                logger.warning("Failed to fetch news for batch %s: %s", ticker_param, exc)
                continue

            results = (data or {}).get("results") or []
            for article in results:
                # Use the first matching hot ticker from this batch for sentiment
                query_ticker = batch[0]
                for t in article.get("tickers") or []:
                    if t in batch:
                        query_ticker = t
                        break

                try:
                    row = _map_article(article, query_ticker)
                except (KeyError, ValueError) as exc:
                    logger.debug("Skipping malformed article: %s", exc)
                    continue

                # deduplicate — keep first mapping (richer sentiment match)
                if row["id"] not in all_rows:
                    all_rows[row["id"]] = row

            logger.info(
                "Batch %d–%d (%s): %d articles",
                i, i + len(batch), ticker_param, len(results),
            )

    try:
        if not all_rows:
            logger.info("No articles fetched")
            return 0

        count = 0
        async with SessionLocal() as db:
            for row in all_rows.values():
                await db.execute(_UPSERT_SQL, row)
                count += 1
            await db.commit()

        logger.info("Upserted %d hot news articles into news_articles", count)
        return count
    finally:
        await engine.dispose()


# ── Google News RSS fallback (zero-cost, no API key) ─────────────────────────

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


async def fetch_google_news_rss(query: str = "stock market") -> list[dict]:
    """Fetch general market news from Google News RSS (no API key, no sentiment).

    Returns a list of dicts with keys: title, link, source, published_at.
    This is the zero-cost fallback when Massive is unavailable.
    """
    url = _GOOGLE_NEWS_RSS.format(query=query.replace(" ", "+"))
    articles: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Google News RSS fetch failed: %s", exc)
            return articles

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        logger.warning("Google News RSS XML parse error: %s", exc)
        return articles

    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        source_el = item.find("source")
        pub_el = item.find("pubDate")

        published_at = None
        if pub_el is not None and pub_el.text:
            try:
                published_at = parsedate_to_datetime(pub_el.text).astimezone(timezone.utc)
            except (ValueError, TypeError):
                pass

        articles.append({
            "title": title_el.text if title_el is not None else "",
            "link": link_el.text if link_el is not None else "",
            "source": source_el.text if source_el is not None else "",
            "published_at": published_at,
        })

    logger.info("Google News RSS: %d articles for query=%r", len(articles), query)
    return articles


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch hot-ticker news from Massive.")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="fetch and print but do not write to DB",
    )
    ap.add_argument(
        "--google-rss", action="store_true",
        help="test the Google News RSS fallback",
    )
    args = ap.parse_args()

    if args.google_rss:
        results = asyncio.run(fetch_google_news_rss())
        for r in results[:10]:
            print(f"  [{r['source']}] {r['title']}")
        print(f"Total: {len(results)}")
    elif args.dry_run:
        # For dry-run, just fetch and log without DB write
        logger.info("DRY RUN — would fetch news for %d hot tickers", len(HOT_TICKERS))
        logger.info("Hot tickers: %s", ", ".join(HOT_TICKERS))
    else:
        count = asyncio.run(fetch_hot_news())
        print(f"Done: {count} articles upserted")
