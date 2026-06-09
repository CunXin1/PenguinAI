"""Fetch news for hot tickers, score with FinBERT, store in news_articles hypertable.

One row per (article, ticker) — same article can have different FinBERT scores for
different tickers because we prepend the ticker to the headline before scoring.

Storage:
  news_articles (hypertable):
    time, ticker, headline, source, url, finbert_score, finbert_label, raw_metadata

Dedup: ON CONFLICT on (time, id) — skips articles already stored for that ticker.

RUN (repo root; needs MASSIVE_API_KEY or FINNHUB_API_KEY in .env):
    python -m data.news.ingest                  # one-shot, all hot tickers
    python -m data.news.ingest --tier 1          # tier-1 only
    python -m data.news.ingest --ticker NVDA     # single ticker
    python -m data.news.ingest --dry-run         # fetch + score, no DB write
"""

import argparse
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.news.constants import HOT_TICKERS_LIST, TIER1_TICKERS, TIER2_TICKERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("news.ingest")

_BATCH_SIZE = 10


# ── Settings loader (works from both backend/ and repo root) ────────────────

def _load_settings():
    from pathlib import Path

    for parent in Path(__file__).resolve().parents:
        env_path = parent / ".env"
        if env_path.is_file():
            vals = {}
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip().strip('"').strip("'")
            return vals
    return {}


_env = _load_settings()
DATABASE_URL = _env.get("DATABASE_URL", "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai")
MASSIVE_API_KEY = _env.get("MASSIVE_API_KEY", "")
MASSIVE_BASE_URL = _env.get("MASSIVE_BASE_URL", "https://api.massive.com").rstrip("/")
FINNHUB_API_KEY = _env.get("FINNHUB_API_KEY", "")
FINNHUB_BASE_URL = _env.get("FINNHUB_BASE_URL", "https://finnhub.io/api/v1")


# ── FinBERT scoring (optional — gracefully skips if torch unavailable) ──────

_finbert = None
_finbert_attempted = False


def _get_finbert():
    global _finbert, _finbert_attempted
    if _finbert_attempted:
        return _finbert
    _finbert_attempted = True
    try:
        from ml.inference.finbert_scorer import FinBERTScorer
        _finbert = FinBERTScorer()
        logger.info("FinBERT scorer loaded")
    except Exception as exc:
        logger.info("FinBERT not available (%s) — using Massive sentiment only", exc)
    return _finbert


def score_articles_finbert(
    articles: list[dict], ticker: str
) -> list[tuple[str | None, float | None]]:
    """Score headlines with FinBERT, prepending ticker for context.

    Returns list of (label, score) tuples aligned with input articles.
    Falls back to Massive sentiment if FinBERT is unavailable.
    """
    scorer = _get_finbert()
    if scorer is None:
        results = []
        for a in articles:
            massive_sent = _extract_massive_sentiment(a, ticker)
            results.append(massive_sent)
        return results

    texts = [f"{ticker}: {a.get('title') or a.get('headline', '')}" for a in articles]
    try:
        scored = scorer.score_batch(texts)
        return [(r.label, r.sentiment) for r in scored]
    except Exception as exc:
        logger.warning("FinBERT scoring failed: %s — falling back to Massive", exc)
        return [_extract_massive_sentiment(a, ticker) for a in articles]


def _extract_massive_sentiment(article: dict, ticker: str) -> tuple[str | None, float | None]:
    """Extract sentiment from Massive insights for a specific ticker."""
    score_map = {"positive": 0.5, "negative": -0.5, "neutral": 0.0}
    for insight in article.get("insights") or []:
        if insight.get("ticker", "").upper() == ticker.upper():
            label = (insight.get("sentiment") or "").lower()
            if label in score_map:
                return label, score_map[label]
    for insight in article.get("insights") or []:
        label = (insight.get("sentiment") or "").lower()
        if label in score_map:
            return label, score_map[label]
    return None, None


# ── Fetch helpers ───────────────────────────────────────────────────────────

async def fetch_massive(
    client: httpx.AsyncClient, tickers: list[str], limit: int = 50
) -> list[dict]:
    if not MASSIVE_API_KEY:
        return []
    ticker_param = ",".join(tickers)
    try:
        resp = await client.get(
            f"{MASSIVE_BASE_URL}/v2/reference/news",
            params={"ticker": ticker_param, "limit": limit},
            headers={"Authorization": f"Bearer {MASSIVE_API_KEY}"},
        )
        if resp.status_code != 200:
            logger.warning("Massive %d for %s", resp.status_code, ticker_param)
            return []
        return (resp.json().get("results") or [])
    except Exception as exc:
        logger.warning("Massive fetch failed for %s: %s", ticker_param, exc)
        return []


async def fetch_finnhub(client: httpx.AsyncClient, ticker: str, days: int = 7) -> list[dict]:
    if not FINNHUB_API_KEY:
        return []
    today = datetime.now(UTC).date()
    from_date = today - timedelta(days=days)
    try:
        resp = await client.get(
            f"{FINNHUB_BASE_URL}/company-news",
            params={
                "symbol": ticker,
                "from": from_date.isoformat(),
                "to": today.isoformat(),
                "token": FINNHUB_API_KEY,
            },
        )
        if resp.status_code != 200:
            return []
        items = resp.json()
        if not isinstance(items, list):
            return []
        for item in items:
            item["_source"] = "finnhub"
        return items
    except Exception as exc:
        logger.warning("Finnhub fetch failed for %s: %s", ticker, exc)
        return []


# ── Article normalization ───────────────────────────────────────────────────

def _parse_ts(raw: str) -> datetime:
    raw = raw.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _article_url(article: dict) -> str:
    return article.get("article_url") or article.get("url") or ""


def _article_time(article: dict) -> datetime | None:
    if article.get("_source") == "finnhub":
        ts = article.get("datetime")
        if ts:
            return datetime.fromtimestamp(ts, tz=UTC)
        return None
    pub = article.get("published_utc")
    if pub:
        try:
            return _parse_ts(pub)
        except (ValueError, TypeError):
            pass
    return None


def _article_headline(article: dict) -> str:
    return article.get("title") or article.get("headline") or ""


def _article_source(article: dict) -> str:
    if article.get("_source") == "finnhub":
        return article.get("source", "Unknown")
    publisher = article.get("publisher") or {}
    return publisher.get("name", "Unknown")


def _article_tickers(article: dict) -> list[str]:
    if article.get("_source") == "finnhub":
        related = article.get("related") or ""
        return [t.strip() for t in related.split(",") if t.strip()]
    return article.get("tickers") or []


def _article_metadata(article: dict) -> dict:
    """Extra fields stored in raw_metadata JSONB."""
    meta = {}
    for key in ("summary", "description", "image_url", "image", "author", "category"):
        val = article.get(key)
        if val:
            meta[key] = val
    publisher = article.get("publisher") or {}
    if publisher.get("name"):
        meta["publisher_name"] = publisher["name"]
    insights = article.get("insights")
    if insights:
        meta["insights"] = insights
    return meta


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


# ── DB upsert ───────────────────────────────────────────────────────────────

_UPSERT_SQL = text("""
    INSERT INTO news_articles (id, time, ticker, headline, source, url, finbert_score, finbert_label, raw_metadata)
    VALUES (:id, :time, :ticker, :headline, :source, :url, :finbert_score, :finbert_label, CAST(:raw_metadata AS jsonb))
    ON CONFLICT (time, id) DO UPDATE SET
        finbert_score = EXCLUDED.finbert_score,
        finbert_label = EXCLUDED.finbert_label,
        raw_metadata  = EXCLUDED.raw_metadata
""")

_CHECK_URL_SQL = text("""
    SELECT 1 FROM news_articles WHERE url = :url AND ticker = :ticker LIMIT 1
""")


async def store_articles(
    session: AsyncSession,
    articles: list[dict],
    ticker: str,
    sentiments: list[tuple[str | None, float | None]],
) -> int:
    """Upsert articles for a single ticker. Returns count of new rows."""
    count = 0
    for article, (label, score) in zip(articles, sentiments, strict=False):
        url = _article_url(article)
        if not url:
            continue

        # Dedup: skip if this (url, ticker) pair already exists
        existing = await session.execute(_CHECK_URL_SQL, {"url": url, "ticker": ticker})
        if existing.scalar_one_or_none() is not None:
            continue

        pub_time = _article_time(article)
        if pub_time is None:
            continue

        headline = _article_headline(article)
        if not headline:
            continue

        row_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{url}:{ticker}")
        meta = _article_metadata(article)

        await session.execute(_UPSERT_SQL, {
            "id": str(row_id),
            "time": pub_time,
            "ticker": ticker,
            "headline": headline,
            "source": _article_source(article),
            "url": url,
            "finbert_score": round(score, 4) if score is not None else None,
            "finbert_label": label,
            "raw_metadata": json.dumps(meta),
        })
        count += 1

    return count


# ── High-level ingest functions ─────────────────────────────────────────────

async def ingest_tickers(
    tickers: list[str],
    db_url: str | None = None,
    dry_run: bool = False,
) -> int:
    """Fetch + score + store news for a list of tickers. Returns total new rows."""
    engine = create_async_engine(db_url or DATABASE_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    total = 0

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Fetch in batches via Massive (supports comma-separated tickers)
            all_articles: dict[str, list[dict]] = {t: [] for t in tickers}

            for i in range(0, len(tickers), _BATCH_SIZE):
                batch = tickers[i:i + _BATCH_SIZE]
                articles = await fetch_massive(client, batch, limit=50)

                if not articles:
                    # Fallback: fetch individually from Finnhub
                    for t in batch:
                        fh = await fetch_finnhub(client, t, days=7)
                        all_articles[t].extend(fh[:20])
                    continue

                # Distribute articles to the tickers they mention
                for article in articles:
                    mentioned = set(t.upper() for t in _article_tickers(article))
                    for t in batch:
                        if t.upper() in mentioned:
                            all_articles[t].append(article)

                logger.info("Fetched %d articles for batch %s", len(articles), ",".join(batch))

            # Score + store per ticker
            for ticker, articles in all_articles.items():
                if not articles:
                    continue

                sentiments = score_articles_finbert(articles, ticker)

                if dry_run:
                    for a, (lbl, sc) in zip(articles, sentiments, strict=False):
                        print(f"  [{lbl or '?':>8} {sc or 0:+.2f}] {ticker}: {_article_headline(a)[:70]}")
                    continue

                async with session_factory() as session:
                    n = await store_articles(session, articles, ticker, sentiments)
                    await session.commit()
                    if n > 0:
                        logger.info("%s: stored %d new articles", ticker, n)
                    total += n

    finally:
        await engine.dispose()

    return total


async def ingest_tier1(db_url: str | None = None) -> int:
    logger.info("Ingesting tier-1 (%d tickers)", len(TIER1_TICKERS))
    return await ingest_tickers(TIER1_TICKERS, db_url)


async def ingest_tier2(db_url: str | None = None) -> int:
    logger.info("Ingesting tier-2 (%d tickers)", len(TIER2_TICKERS))
    return await ingest_tickers(TIER2_TICKERS, db_url)


async def ingest_all(db_url: str | None = None) -> int:
    logger.info("Ingesting all hot tickers (%d)", len(HOT_TICKERS_LIST))
    return await ingest_tickers(HOT_TICKERS_LIST, db_url)


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch + score + store hot-ticker news.")
    ap.add_argument("--tier", type=int, choices=[1, 2], help="Fetch only tier 1 or 2")
    ap.add_argument("--ticker", type=str, help="Fetch a single ticker")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + score only, no DB write")
    args = ap.parse_args()

    if args.ticker:
        count = asyncio.run(ingest_tickers([args.ticker.upper()], dry_run=args.dry_run))
    elif args.tier == 1:
        count = asyncio.run(ingest_tier1() if not args.dry_run else ingest_tickers(TIER1_TICKERS, dry_run=True))
    elif args.tier == 2:
        count = asyncio.run(ingest_tier2() if not args.dry_run else ingest_tickers(TIER2_TICKERS, dry_run=True))
    else:
        count = asyncio.run(ingest_all() if not args.dry_run else ingest_tickers(HOT_TICKERS_LIST, dry_run=True))

    print(f"Done: {count} new articles stored")
