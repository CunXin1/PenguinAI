"""
News API — 3-tier fallback: Massive (primary) → Google News RSS (secondary) → Finnhub (backup).

Hot tickers (Nasdaq-100 + key ETFs) are pre-fetched by Celery and served from the
``news_articles`` table.  Cold tickers are fetched on-demand and cached in-memory.
"""

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from data.news.constants import HOT_TICKERS_SET as HOT_TICKERS

router = APIRouter()
logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

# ── In-memory cache ──────────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}
_MARKET_TTL = 300.0   # 5 minutes
_COMPANY_TTL = 600.0  # 10 minutes


def _get_cached(key: str, ttl: float) -> list | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > ttl:
        del _cache[key]
        return None
    return data


def _set_cache(key: str, data: list) -> None:
    _cache[key] = (time.monotonic(), data)


# ── Mappers ──────────────────────────────────────────────────────────

def _map_massive_article(item: dict) -> dict:
    """Map a Massive ``results[]`` item to the unified response format."""
    # Parse published_utc → unix timestamp
    ts = 0
    pub = item.get("published_utc")
    if pub:
        try:
            ts = int(datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp())
        except (ValueError, TypeError):
            ts = 0

    # Sentiment: pick the first insight's sentiment if available
    sentiment = None
    sentiment_score = None
    insights = item.get("insights") or []
    if insights:
        sentiment = insights[0].get("sentiment")
        # Massive doesn't return a numeric score directly

    publisher = item.get("publisher") or {}

    return {
        "id": f"massive:{item.get('id', '')}",
        "headline": item.get("title", ""),
        "summary": item.get("description"),
        "source": publisher.get("name", "Unknown"),
        "url": item.get("article_url"),
        "image": item.get("image_url"),
        "datetime": ts,
        "tickers": item.get("tickers") or [],
        "category": "general",
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
    }


def _map_finnhub_article(item: dict) -> dict:
    """Map a Finnhub news item to the unified response format."""
    return {
        "id": f"finnhub:{item.get('id', '')}",
        "headline": item.get("headline", ""),
        "summary": item.get("summary"),
        "source": item.get("source", "Unknown"),
        "url": item.get("url"),
        "image": item.get("image") or None,
        "datetime": item.get("datetime", 0),
        "tickers": [t.strip() for t in (item.get("related") or "").split(",") if t.strip()],
        "category": item.get("category", "general"),
        "sentiment": None,
        "sentiment_score": None,
    }


def _map_google_article(item: dict) -> dict:
    """Map a parsed Google News RSS ``<item>`` dict to the unified response format."""
    ts = 0
    pub = item.get("pubDate")
    if pub:
        try:
            ts = int(parsedate_to_datetime(pub).timestamp())
        except (ValueError, TypeError):
            ts = 0

    return {
        "id": f"google:{hashlib.md5(item.get('link', '').encode()).hexdigest()[:12]}",
        "headline": item.get("title", ""),
        "summary": None,
        "source": item.get("source", "Google News"),
        "url": item.get("link"),
        "image": None,
        "datetime": ts,
        "tickers": [],
        "category": "general",
        "sentiment": None,
        "sentiment_score": None,
    }


def _map_db_row(row) -> dict:
    """Map a ``news_articles`` DB row (as mapping) to the API response format."""
    ts = 0
    pub = row.get("published_at") or row.get("published_utc")
    if pub is not None:
        try:
            if isinstance(pub, datetime):
                ts = int(pub.timestamp())
            else:
                ts = int(datetime.fromisoformat(str(pub)).timestamp())
        except (ValueError, TypeError):
            ts = 0

    score = row.get("sentiment_score")
    return {
        "id": row["id"],
        "headline": row["headline"],
        "summary": row.get("summary"),
        "source": row.get("publisher_name", "Unknown"),
        "url": row.get("article_url"),
        "image": row.get("image_url"),
        "datetime": ts,
        "tickers": list(row.get("tickers") or []),
        "category": row.get("category", "general"),
        "sentiment": row.get("sentiment"),
        "sentiment_score": float(score) if score is not None else None,
    }


# ── Fetch helpers (each returns None on failure) ─────────────────────

async def _fetch_massive_news(
    ticker: str | None = None,
    limit: int = 50,
) -> list[dict] | None:
    """Fetch from Massive API. Returns None on any failure."""
    if not settings.MASSIVE_API_KEY:
        return None
    params: dict = {"limit": limit}
    if ticker:
        params["ticker"] = ticker
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.MASSIVE_BASE_URL}/v2/reference/news",
                params=params,
                headers={"Authorization": f"Bearer {settings.MASSIVE_API_KEY}"},
            )
        if resp.status_code != 200:
            logger.warning("Massive news returned %d: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        results = data.get("results") or []
        return [_map_massive_article(item) for item in results[:limit]]
    except Exception as exc:
        logger.warning("Massive news fetch failed: %r", exc)
        return None


async def _fetch_google_rss(
    query: str = "stock market finance",
    limit: int = 50,
) -> list[dict] | None:
    """Parse Google News RSS feed. Returns None on any failure."""
    url = (
        f"https://news.google.com/rss/search"
        f"?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("Google News RSS returned %d", resp.status_code)
            return None

        root = ET.fromstring(resp.text)
        articles: list[dict] = []
        for item_el in root.iter("item"):
            parsed: dict[str, str | None] = {}
            for field in ("title", "link", "pubDate"):
                el = item_el.find(field)
                parsed[field] = el.text if el is not None else None
            source_el = item_el.find("source")
            parsed["source"] = source_el.text if source_el is not None else "Google News"
            articles.append(_map_google_article(parsed))
            if len(articles) >= limit:
                break
        return articles
    except Exception as exc:
        logger.warning("Google News RSS fetch failed: %r", exc)
        return None


async def _fetch_finnhub_news(
    ticker: str | None = None,
    category: str = "general",
    limit: int = 50,
) -> list[dict] | None:
    """Fetch from Finnhub. Returns None on any failure."""
    if not settings.FINNHUB_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if ticker:
                today = datetime.now(UTC).date()
                from_date = today - timedelta(days=30)
                resp = await client.get(
                    f"{settings.FINNHUB_BASE_URL}/company-news",
                    params={
                        "symbol": ticker,
                        "from": from_date.isoformat(),
                        "to": today.isoformat(),
                        "token": settings.FINNHUB_API_KEY,
                    },
                )
            else:
                resp = await client.get(
                    f"{settings.FINNHUB_BASE_URL}/news",
                    params={
                        "category": category,
                        "token": settings.FINNHUB_API_KEY,
                    },
                )
        if resp.status_code != 200:
            logger.warning("Finnhub news returned %d: %s", resp.status_code, resp.text[:200])
            return None
        items = resp.json()
        if not isinstance(items, list):
            return None
        return [_map_finnhub_article(item) for item in items[:limit]]
    except Exception as exc:
        logger.warning("Finnhub news fetch failed: %r", exc)
        return None


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/market")
async def get_market_news(
    limit: int = Query(default=30, ge=1, le=100),
):
    """
    General market news for the feed page.

    Source priority: Massive → Google News RSS → Finnhub.
    Result is cached in-memory for 5 minutes.
    """
    cache_key = f"market:{limit}"
    cached = _get_cached(cache_key, _MARKET_TTL)
    if cached is not None:
        return cached

    # Tier 1: Massive
    articles = await _fetch_massive_news(ticker=None, limit=limit)

    # Tier 2: Google News RSS
    if articles is None:
        articles = await _fetch_google_rss(query="stock market finance", limit=limit)

    # Tier 3: Finnhub
    if articles is None:
        articles = await _fetch_finnhub_news(ticker=None, category="general", limit=limit)

    # All failed
    if articles is None:
        articles = []

    articles = articles[:limit]
    _set_cache(cache_key, articles)
    return articles


@router.get("/hot")
async def get_hot_news(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    ticker: str | None = Query(default=None),
):
    """
    Pre-stored hot news from the DB (for dashboard + ML pipeline).

    Returns articles marked ``is_hot = TRUE`` from the last 7 days.
    Optionally filtered by ticker using the PostgreSQL ``@>`` array-contains operator.
    """
    if ticker:
        t = ticker.upper()
        if not _TICKER_RE.match(t):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid ticker format",
            )
        rows = await db.execute(
            text(
                "SELECT * FROM news_articles "
                "WHERE is_hot = TRUE "
                "  AND published_at > NOW() - INTERVAL '7 days' "
                "  AND tickers @> ARRAY[:ticker]::TEXT[] "
                "ORDER BY published_at DESC "
                "LIMIT :limit"
            ),
            {"ticker": t, "limit": limit},
        )
    else:
        rows = await db.execute(
            text(
                "SELECT * FROM news_articles "
                "WHERE is_hot = TRUE "
                "  AND published_at > NOW() - INTERVAL '7 days' "
                "ORDER BY published_at DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        )
    return [_map_db_row(r) for r in rows.mappings()]


@router.get("/{ticker}")
async def get_company_news(
    ticker: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=20, ge=1, le=50),
):
    """
    News for a specific ticker.

    Hot tickers are served from the DB (pre-fetched by Celery).
    Cold tickers are fetched on-demand via the 3-tier fallback and cached for 10 minutes.
    """
    t = ticker.upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid ticker format",
        )

    # ── Hot ticker → query DB ────────────────────────────────────
    if t in HOT_TICKERS:
        rows = await db.execute(
            text(
                "SELECT * FROM news_articles "
                "WHERE :ticker = ANY(tickers) "
                "  AND published_at > NOW() - make_interval(days => :days) "
                "ORDER BY published_at DESC "
                "LIMIT :limit"
            ),
            {"ticker": t, "days": days, "limit": limit},
        )
        return [_map_db_row(r) for r in rows.mappings()]

    # ── Cold ticker → on-demand fetch with in-memory cache ───────
    cache_key = f"company:{t}"
    cached = _get_cached(cache_key, _COMPANY_TTL)
    if cached is not None:
        return cached[:limit]

    # Tier 1: Massive
    articles = await _fetch_massive_news(ticker=t, limit=limit)

    # Tier 2: Finnhub (Google RSS is not useful for single-ticker queries)
    if articles is None:
        articles = await _fetch_finnhub_news(ticker=t, limit=limit)

    if articles is None:
        articles = []

    articles = articles[:limit]
    _set_cache(cache_key, articles)
    return articles
