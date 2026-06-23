"""Fetch news for hot tickers, score with FinBERT, store in news_articles hypertable.

Sources (merged every cycle, deduped by (url, ticker) downstream):
  1. Massive API (paid)  — ticker-tagged, carries summary/image/sentiment insights
  2. Google News RSS     — free, no key, near-real-time (the SAME source the chat
                           agent's web_fetch_news uses); fetched per ticker on EVERY
                           cycle, not just as a fallback, so the DB tracks the chat
                           agent's freshness instead of lagging behind it
  3. Finnhub REST        — FREE TIER, 60 req/min — last resort only, for tickers that
                           got nothing from Massive or Google (save quota)

One row per (article, ticker) — same article can have different FinBERT scores for
different tickers because we prepend the ticker to the headline before scoring.

Dedup: ON CONFLICT on (time, id) — skips articles already stored for that ticker.

RUN (repo root):
    python -m data.news.ingest                  # one-shot, all hot tickers
    python -m data.news.ingest --tier 1          # tier-1 only
    python -m data.news.ingest --ticker NVDA     # single ticker
    python -m data.news.ingest --dry-run         # fetch + score, no DB write
"""

import argparse
import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.news.constants import HOT_TICKERS_LIST, MAX_ARTICLES_PER_TICKER, TIER1_TICKERS, TIER2_TICKERS

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
# Prefer the real OS environment over the .env file: inside a container the
# compose `environment:` block sets DATABASE_URL to the `timescaledb` service
# host, which must win over the localhost default baked into .env.
DATABASE_URL = os.environ.get("DATABASE_URL") or _env.get(
    "DATABASE_URL", "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
)
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


# ── Rate limiter ────────────────────────────────────────────────────────────

class _RateLimiter:
    """Simple async rate limiter — enforces minimum interval between calls."""

    def __init__(self, calls_per_sec: float):
        self._interval = 1.0 / calls_per_sec
        self._last = 0.0

    async def wait(self):
        import time as _time
        now = _time.monotonic()
        gap = self._interval - (now - self._last)
        if gap > 0:
            await asyncio.sleep(gap)
        self._last = _time.monotonic()


# Massive paid: stress test showed 54+ req/min with zero throttling.
# No artificial delay — network latency (~1s/call) is the natural limiter.
_massive_limiter = None
# Finnhub free: 60 req/min, use 25/min to leave headroom for the API route
_finnhub_limiter = _RateLimiter(25.0 / 60.0)


# ── Fetch helpers ───────────────────────────────────────────────────────────

async def fetch_massive(
    client: httpx.AsyncClient, tickers: list[str], limit: int = 50
) -> list[dict]:
    """Fetch news from Massive. Uses ticker.any_of for batches, ticker for single."""
    if not MASSIVE_API_KEY:
        return []
    if _massive_limiter:
        await _massive_limiter.wait()
    if len(tickers) == 1:
        params = {"ticker": tickers[0], "limit": limit}
    else:
        params = {"ticker.any_of": ",".join(tickers), "limit": limit}
    try:
        resp = await client.get(
            f"{MASSIVE_BASE_URL}/v2/reference/news",
            params=params,
            headers={"Authorization": f"Bearer {MASSIVE_API_KEY}"},
        )
        if resp.status_code == 429:
            logger.warning("Massive rate limited — backing off 30s")
            await asyncio.sleep(30)
            return []
        if resp.status_code != 200:
            logger.warning("Massive %d for %s", resp.status_code, ",".join(tickers))
            return []
        return (resp.json().get("results") or [])
    except Exception as exc:
        logger.warning("Massive fetch failed for %s: %s", ",".join(tickers), exc)
        return []


async def fetch_google_rss(client: httpx.AsyncClient, tickers: list[str], limit: int = 30) -> list[dict]:
    """Fetch from Google News RSS. Free, no key, but no sentiment or ticker filtering."""
    query = "+".join(f"{t}+stock" for t in tickers[:3])
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    try:
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime as _parse_rfc2822

        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200:
            logger.warning("Google RSS %d for %s", resp.status_code, query)
            return []
        root = ET.fromstring(resp.text)
        articles = []
        for item_el in root.iter("item"):
            title_el = item_el.find("title")
            link_el = item_el.find("link")
            source_el = item_el.find("source")
            pub_el = item_el.find("pubDate")
            pub_ts = None
            if pub_el is not None and pub_el.text:
                try:
                    dt = _parse_rfc2822(pub_el.text)
                    if dt.tzinfo is None:
                        from datetime import timezone
                        dt = dt.replace(tzinfo=timezone.utc)
                    pub_ts = dt.isoformat()
                except (ValueError, TypeError):
                    pass
            articles.append({
                "title": title_el.text if title_el is not None else "",
                "article_url": link_el.text if link_el is not None else "",
                "published_utc": pub_ts,
                "publisher": {"name": source_el.text if source_el is not None else "Google News"},
                "tickers": [],
                "_source": "google",
            })
            if len(articles) >= limit:
                break
        return articles
    except Exception as exc:
        logger.warning("Google RSS fetch failed for %s: %s", query, exc)
        return []


async def fetch_finnhub(client: httpx.AsyncClient, ticker: str, days: int = 7) -> list[dict]:
    if not FINNHUB_API_KEY:
        return []
    await _finnhub_limiter.wait()
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
        if resp.status_code == 429:
            logger.warning("Finnhub rate limited for %s — backing off", ticker)
            await asyncio.sleep(10)
            return []
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
    # Google RSS: published_utc is already ISO from our parser
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


# ── Cross-source dedup ────────────────────────────────────────────────────────

def _norm_headline(text: str) -> str:
    """Lowercased, whitespace-collapsed headline — the cross-source dedup key."""
    return " ".join(str(text or "").lower().split())


def _is_massive(article: dict) -> bool:
    """Massive articles carry no ``_source`` tag (Google/Finnhub set it)."""
    return article.get("_source") not in ("google", "finnhub")


def _dedup_articles(articles: list[dict]) -> list[dict]:
    """Collapse the same story across sources, keeping the Massive copy when duplicated.

    Massive and Google return different URLs for the same article (canonical vs Google
    redirect), so url-only dedup misses them. We key on the normalized headline and, on a
    collision, prefer the Massive row (it carries summary/image/ticker tags) over the
    Google/Finnhub headline-only dup. Order is first-seen (input is newest-first).
    """
    best: dict[str, dict] = {}
    order: list[str] = []
    for a in articles:
        key = _norm_headline(_article_headline(a)) or _article_url(a)
        if not key:
            continue
        cur = best.get(key)
        if cur is None:
            best[key] = a
            order.append(key)
        elif _is_massive(a) and not _is_massive(cur):
            best[key] = a  # replace a Google/Finnhub dup with the richer Massive copy
    return [best[k] for k in order]


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

_PRUNE_SQL = text("""
    DELETE FROM news_articles
    WHERE ticker = :ticker
      AND time < (
          SELECT time FROM news_articles
          WHERE ticker = :ticker
          ORDER BY time DESC
          OFFSET :keep LIMIT 1
      )
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
    include_massive: bool = True,
) -> int:
    """Fetch + score + store news for a list of tickers. Returns total new rows.

    Massive and Google News RSS are PEER sources: both are fetched and merged on every
    cycle (the scheduler always enables Massive), so the feed has full volume — Massive
    adds summary/image/ticker tags, Google adds free, near-real-time breadth. Overlap is
    deduped downstream by (url, ticker). ``include_massive=False`` is only for the
    ``--google-only`` CLI / manual runs (pure Google pass + Finnhub last-resort).
    """
    engine = create_async_engine(db_url or DATABASE_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    total = 0

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            all_articles: dict[str, list[dict]] = {t: [] for t in tickers}

            for i in range(0, len(tickers), _BATCH_SIZE):
                batch = tickers[i:i + _BATCH_SIZE]

                # Peer sources, merged every cycle (not fallback-ranked):
                #   - Google RSS: one ticker-scoped query per ticker — free, near-real-time
                #     (the same source the chat agent uses); maps straight to each ticker.
                #   - Massive: one batched call (ticker.any_of), rich summary/image/tags.
                # Both run every cycle so the feed has full volume; overlap is cheap because
                # store_articles dedups by (url, ticker). include_massive=False is CLI-only.
                if include_massive:
                    massive_articles, *google_per_ticker = await asyncio.gather(
                        fetch_massive(client, batch, limit=50),
                        *(fetch_google_rss(client, [t], limit=15) for t in batch),
                    )
                else:
                    massive_articles = []
                    google_per_ticker = list(
                        await asyncio.gather(*(fetch_google_rss(client, [t], limit=15) for t in batch))
                    )

                # Massive: distribute by each article's ticker tags (headline-scan
                # only as a fallback for the rare untagged article).
                for article in massive_articles or []:
                    mentioned = {t.upper() for t in _article_tickers(article)}
                    if mentioned:
                        for t in batch:
                            if t.upper() in mentioned:
                                all_articles[t].append(article)
                    else:
                        headline = _article_headline(article).upper()
                        for t in batch:
                            if t.upper() in headline:
                                all_articles[t].append(article)

                # Google RSS: each query is ticker-scoped, so map results straight to it.
                for t, g_articles in zip(batch, google_per_ticker, strict=False):
                    all_articles[t].extend(g_articles)

                # Finnhub: last resort — only for tickers still empty after both sources.
                starved = [t for t in batch if not all_articles[t]]
                if starved:
                    for t in starved:
                        fh = await fetch_finnhub(client, t, days=7)
                        all_articles[t].extend(fh[:20])
                    logger.info(
                        "Batch %s: Finnhub fallback for %d ticker(s)", ",".join(batch), len(starved)
                    )

                n_google = sum(len(g) for g in google_per_ticker)
                logger.info(
                    "Fetched batch %s — Massive=%d, Google RSS=%d",
                    ",".join(batch), len(massive_articles or []), n_google,
                )

            # Score + store per ticker
            for ticker, articles in all_articles.items():
                if not articles:
                    continue

                # Collapse the same story across Massive + Google (prefer the Massive copy)
                # before scoring/storing, so the DB doesn't carry duplicate rows per ticker.
                articles = _dedup_articles(articles)

                sentiments = score_articles_finbert(articles, ticker)

                if dry_run:
                    for a, (lbl, sc) in zip(articles, sentiments, strict=False):
                        print(f"  [{lbl or '?':>8} {sc or 0:+.2f}] {ticker}: {_article_headline(a)[:70]}")
                    continue

                async with session_factory() as session:
                    n = await store_articles(session, articles, ticker, sentiments)
                    # Prune excess — keep only the newest MAX_ARTICLES_PER_TICKER
                    await session.execute(
                        _PRUNE_SQL, {"ticker": ticker, "keep": MAX_ARTICLES_PER_TICKER}
                    )
                    await session.commit()
                    if n > 0:
                        logger.info("%s: stored %d new articles", ticker, n)
                    total += n

    finally:
        await engine.dispose()

    return total


async def ingest_tier1(db_url: str | None = None, include_massive: bool = True) -> int:
    logger.info("Ingesting tier-1 (%d tickers, massive=%s)", len(TIER1_TICKERS), include_massive)
    return await ingest_tickers(TIER1_TICKERS, db_url, include_massive=include_massive)


async def ingest_tier2(db_url: str | None = None, include_massive: bool = True) -> int:
    logger.info("Ingesting tier-2 (%d tickers, massive=%s)", len(TIER2_TICKERS), include_massive)
    return await ingest_tickers(TIER2_TICKERS, db_url, include_massive=include_massive)


async def ingest_all(db_url: str | None = None, include_massive: bool = True) -> int:
    logger.info("Ingesting all hot tickers (%d, massive=%s)", len(HOT_TICKERS_LIST), include_massive)
    return await ingest_tickers(HOT_TICKERS_LIST, db_url, include_massive=include_massive)


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch + score + store hot-ticker news.")
    ap.add_argument("--tier", type=int, choices=[1, 2], help="Fetch only tier 1 or 2")
    ap.add_argument("--ticker", type=str, help="Fetch a single ticker")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + score only, no DB write")
    ap.add_argument(
        "--google-only", action="store_true",
        help="Skip Massive — pure Google RSS pass (free, near-real-time)",
    )
    args = ap.parse_args()
    inc_massive = not args.google_only

    if args.ticker:
        count = asyncio.run(
            ingest_tickers([args.ticker.upper()], dry_run=args.dry_run, include_massive=inc_massive)
        )
    elif args.tier == 1:
        count = asyncio.run(ingest_tickers(TIER1_TICKERS, dry_run=args.dry_run, include_massive=inc_massive))
    elif args.tier == 2:
        count = asyncio.run(ingest_tickers(TIER2_TICKERS, dry_run=args.dry_run, include_massive=inc_massive))
    else:
        count = asyncio.run(ingest_tickers(HOT_TICKERS_LIST, dry_run=args.dry_run, include_massive=inc_massive))

    print(f"Done: {count} new articles stored")
