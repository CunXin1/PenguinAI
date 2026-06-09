# News Module

> Last updated: 2026-06-09

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Sources                             │
│  Massive API (primary)  Google News RSS (secondary)  Finnhub    │
│  - sentiment included   - free, no key               - backup   │
│  - ticker filtering     - no sentiment               - 60/min   │
│  - publisher details    - no ticker filter            - no sent. │
└──────┬──────────────────────┬─────────────────────────┬─────────┘
       │                      │                         │
       ▼                      ▼                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Backend (/api/news)                          │
│  3-tier fallback: Massive → Google RSS → Finnhub                │
│                                                                  │
│  /market  → general feed (cached 5 min)                         │
│  /hot     → DB-stored Nasdaq-100/ETF news (for ML)              │
│  /{ticker}→ hot=DB, cold=on-demand Massive→Finnhub (cached 10m) │
└──────────────────────┬───────────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
  News Feed       Signal Detail    Dashboard
  /news           /signals/[t]     NewsPreview
  (full page)     (5 articles)     (5 articles)
```

## Hot vs Cold Tickers

| Tier | Tickers | Source | Storage | TTL | Use Case |
|------|---------|--------|---------|-----|----------|
| **Hot** | ~84 (Nasdaq-100 + key ETFs) | Massive API | `news_articles` table | Celery every 30 min | ML pipeline, dashboard, `/hot` endpoint |
| **Cold** | Everything else | Massive → Finnhub | In-memory cache only | 10 min | On-demand `/news/{ticker}` requests |

Hot ticker list is defined once in `data/news/constants.py` and imported by both the ingestion task and the API route.

## Database Schema

```sql
-- db/schema/03_relational.sql
CREATE TABLE news_articles (
    id              TEXT        PRIMARY KEY,   -- "massive:12345" or "finnhub:67890"
    source_provider TEXT        NOT NULL,      -- massive | finnhub | google
    source_id       TEXT        NOT NULL,      -- original ID from provider
    headline        TEXT        NOT NULL,
    summary         TEXT,
    article_url     TEXT,
    image_url       TEXT,
    author          TEXT,
    publisher_name  TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    tickers         TEXT[]      DEFAULT '{}',  -- related tickers
    category        TEXT        DEFAULT 'general',
    sentiment       TEXT,                      -- positive | negative | neutral
    sentiment_score NUMERIC(5,4),              -- -1.0 to 1.0 (for ML features)
    sentiment_reasoning TEXT,                  -- Massive insight text
    is_hot          BOOLEAN     NOT NULL DEFAULT FALSE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Indexes:**
- `published_at DESC` — time-range queries
- GIN on `tickers` — array-contains filtering
- Partial on `is_hot = TRUE, published_at DESC` — hot news dashboard
- Partial on `sentiment IS NOT NULL` — ML feature queries
- Unique on `(source_provider, source_id)` — deduplication

## API Endpoints

### `GET /api/news/market`

General market news for the news feed page.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 30 | Max articles (1-100) |

**Fallback chain:** Massive → Google News RSS → Finnhub → empty list.
Cached in-memory for 5 minutes (always fetches 100 internally, slices on return).

### `GET /api/news/hot`

Pre-stored hot news from the DB. Used by dashboard and ML pipeline.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max articles (1-200) |
| `ticker` | str | null | Filter by ticker (uses `@>` array-contains) |

Returns `is_hot = TRUE` articles from the last 7 days.

### `GET /api/news/{ticker}`

News for a specific ticker. Branches on hot vs cold:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 7 | Lookback window (1-30) |
| `limit` | int | 20 | Max articles (1-50) |

- **Hot ticker** → queries `news_articles` table directly
- **Cold ticker** → fetches on-demand (Massive → Finnhub), cached 10 min

### Unified Response Shape

All endpoints return the same article format:

```json
{
  "id": "massive:abc123",
  "headline": "Apple Beats Q2 Estimates",
  "summary": "Apple reported...",
  "source": "CNBC",
  "url": "https://cnbc.com/...",
  "image": "https://image.cnbc.com/...",
  "datetime": 1717848000,
  "tickers": ["AAPL"],
  "category": "general",
  "sentiment": "positive",
  "sentiment_score": 0.5
}
```

## Ingestion Pipeline

### Celery Task: `refresh_hot_news`

- **Schedule:** Every 30 minutes (`:15` and `:45`)
- **Queue:** `default`
- **Source:** Massive API (`/v2/reference/news?ticker=AAPL,MSFT,...&limit=50`)
- **Process:**
  1. Batch HOT_TICKERS in groups of 10
  2. Fetch news from Massive with rate limiting (5 req/sec)
  3. Extract sentiment from `insights[]` (prefer ticker-matched insight)
  4. Map sentiment to score: positive=0.5, negative=-0.5, neutral=0.0
  5. Deduplicate by article ID across batches
  6. Upsert into `news_articles` (`ON CONFLICT` updates sentiment + `fetched_at`)

### Manual Run

```bash
python -m data.news.ingest              # full run
python -m data.news.ingest --dry-run    # print tickers only
python -m data.news.ingest --google-rss # test Google RSS fallback
```

## File Structure

```
data/news/
├── __init__.py
├── constants.py          # HOT_TICKERS_LIST, HOT_TICKERS_SET (single source of truth)
└── ingest.py             # fetch_hot_news(), fetch_google_news_rss(), CLI

backend/app/
├── api/routes/news.py    # /market, /hot, /{ticker} endpoints
└── models/news_article.py # SQLAlchemy model

ml/tasks/
├── celery_app.py          # beat_schedule includes refresh-hot-news
└── realtime_ingest.py     # refresh_hot_news Celery task wrapper
```

## Frontend Integration

### News Feed Page (`/news`)

- Fetches `GET /api/news/market` via React Query (5-min stale time)
- Falls back to `MOCK_NEWS` if API unavailable
- Real articles link externally (`target="_blank"` + ExternalLink icon)
- Sentiment filter tabs (all/bullish/bearish/neutral)
- Featured card with thumbnail image

### Signal Detail Page (`/signals/[ticker]`)

- Fetches `GET /api/news/{ticker}?days=7` via React Query
- Shows up to 5 articles below the SignalCard
- Only renders when view is "live" or "demo" and articles exist
- Graceful — section hidden if no news

### Dashboard Widget (NewsPreview)

- Fetches `GET /api/news/market` via React Query (5-min stale time)
- Shows 5 compact article rows with sentiment dots
- Falls back to `MOCK_NEWS`

## Fallback Behavior

| Scenario | /market | /{hot_ticker} | /{cold_ticker} |
|----------|---------|---------------|----------------|
| Massive up | Massive articles + sentiment | DB (pre-fetched) | Massive on-demand |
| Massive down | Google RSS (no sentiment) | DB (stale OK) | Finnhub on-demand |
| All APIs down | Empty list | DB (stale OK) | Empty list |
| Frontend: API fails | MOCK_NEWS fallback | Section hidden | Section hidden |

## Env Vars

| Variable | Required | Description |
|----------|----------|-------------|
| `MASSIVE_API_KEY` | For primary source | Massive API key (also used for minute data) |
| `MASSIVE_BASE_URL` | No | Default `https://api.massive.com` |
| `FINNHUB_API_KEY` | For backup source | Finnhub API key (also used for earnings) |
| `FINNHUB_BASE_URL` | No | Default `https://finnhub.io/api/v1` |

Neither key is strictly required — the system degrades gracefully. Google News RSS needs no key.
