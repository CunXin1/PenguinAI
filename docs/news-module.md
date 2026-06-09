# News Module

> Last updated: 2026-06-09

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                          Data Sources                                 │
│  Massive API (PRIMARY)   Google News RSS (2nd)     Finnhub (BACKUP)  │
│  - paid, no rate limit   - free, no key            - FREE tier       │
│  - sentiment via insights- no sentiment            - 60 req/min      │
│  - ticker.any_of batch   - no ticker filter        - save quota!     │
└──────┬───────────────────────────┬──────────────────────────┬────────┘
       │                          │                          │
       ▼                          ▼                          ▼
┌───────────────────────────────────────────────────────────────────────┐
│                     FinBERT Scorer (local, GPU)                       │
│  Prepends ticker to headline: "NVDA: Intel surges..." → per-ticker   │
│  sentiment. Batch=32 on 4090 → ~50ms/batch. Falls back to Massive    │
│  insights if torch unavailable.                                      │
└──────────────────────────┬────────────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────────────┐
│              news_articles (TimescaleDB hypertable)                   │
│  One row per (article, ticker) — same URL can have different          │
│  finbert_score for NVDA vs INTC. Per-ticker cap (default 50).        │
│  Auto-pruned at 90 days via retention policy.                        │
└──────────────────────────┬────────────────────────────────────────────┘
                           │
       ┌───────────────────┼──────────────────┐
       ▼                   ▼                  ▼
  /api/news/hot      /api/news/{ticker}   /api/news/market
  (DB → fallback)    (DB → fallback)      (Massive → Google → Finnhub)
       │                   │
       ▼                   ▼
  /news page          /signals/[ticker]
  (diversified:        (6 articles +
   max 3/ticker)        sentiment bar)
```

## Source Priority

**Massive API** is the primary source (paid plan, stress-tested at 54+ req/min with zero throttling). **Google News RSS** is the free secondary (no API key, no sentiment, general headlines). **Finnhub REST** is last resort only — its free tier (60 req/min) is shared with earnings calendar, realtime WebSocket auth, and symbol validation.

| Source | Cost | Rate Limit | Sentiment | Ticker Filter | When Used |
|--------|------|-----------|-----------|---------------|-----------|
| Massive | Paid | ~54+/min (tested) | insights[] | `ticker.any_of` batch | Always first |
| Google RSS | Free | None | No | Query-based only | Massive down |
| Finnhub | Free tier | 60/min (shared!) | No | Per-ticker only | Both above fail |

## Fetch Tiers

| Tier | Tickers | Count | Interval | Use Case |
|------|---------|-------|----------|----------|
| **Tier-1** | MAG7 + SPY/QQQ/DIA/IWM/SOXX | 12 | Every 15 min (configurable) | Most-viewed stocks, need freshest data |
| **Tier-2** | Rest of Nasdaq-100 + key ETFs | ~81 | Every 60 min (configurable) | Broad coverage, less time-sensitive |
| **Cold** | Everything else | ∞ | On-demand | User clicks → API fetch → cache 10 min, no DB |

Tier definitions + intervals: `data/news/constants.py` (reads from `.env`)

## Storage Limits

| Limit | Default | Env Var | Purpose |
|-------|---------|---------|---------|
| Max articles per ticker in DB | 50 | `NEWS_MAX_PER_TICKER` | Prevents table bloat; excess pruned after each ingest |
| Max articles per ticker on /news feed | 3 | `NEWS_MAX_PER_TICKER_FEED` / `NEXT_PUBLIC_...` | Diversifies the feed so no single ticker dominates |
| Articles shown on /signals/[ticker] | 6 | — (hardcoded) | Latest headlines with sentiment badges |
| Retention policy | 90 days | — (TimescaleDB `drop_chunks`) | Old headlines stale, sentiment priced in |

**Pruning SQL**: after each ingest cycle, per ticker: `DELETE WHERE time < (SELECT time ... OFFSET :keep LIMIT 1)`. Keeps the N newest rows.

## Database Schema

```sql
-- db/schema/02_timeseries.sql (actual running schema)
CREATE TABLE news_articles (
    id            UUID            NOT NULL DEFAULT uuid_generate_v4(),
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT,                        -- one row per (article, ticker) pair
    headline      TEXT            NOT NULL,
    source        TEXT,
    url           TEXT,
    finbert_score NUMERIC(5, 4),              -- -1.0 to 1.0 (ticker-specific)
    finbert_label TEXT,                        -- positive | negative | neutral
    embedding     VECTOR(384),
    raw_metadata  JSONB,                       -- summary, image_url, insights, etc.
    PRIMARY KEY (time, id)
);
-- Hypertable, auto-partitioned by time
-- Retention policy: 90 days (auto drop_chunks)
```

**Indexes:**
- `(ticker, time DESC)` — per-ticker time-range queries
- `(url)` — general dedup lookups
- `(url, ticker)` — per-ticker dedup (same article, different tickers)
- `(ticker, finbert_label)` partial WHERE NOT NULL — sentiment aggregation queries

## Ingestion Pipeline

### Scheduler (`data/news/scheduler.py`)

Runs as a backend lifespan thread (same pattern as earnings, celebrity holdings):
1. **Startup**: full ingest of all ~93 hot tickers
2. **Every TIER1_INTERVAL** (default 15 min): tier-1 only (12 tickers)
3. **Every TIER2_INTERVAL** (default 60 min): tier-1 + tier-2 (all 93)

The tick ratio is dynamically computed: `tier2_every_n = round(TIER2_INTERVAL / TIER1_INTERVAL)`.

### Ingest Flow (`data/news/ingest.py`)

```
For each batch of 10 tickers:
  1. fetch_massive(batch, limit=50)          # ticker.any_of=NVDA,AAPL,...
     └─ if empty → fetch_google_rss(batch)   # free fallback (UTC-forced timestamps)
        └─ if empty → fetch_finnhub(each)    # last resort, rate-limited 25/min
  2. Distribute articles to tickers they mention
  3. FinBERT score each headline per ticker:
     "NVDA: Intel Surges on Google Foundry Order" → negative for NVDA
     "INTC: Intel Surges on Google Foundry Order" → positive for INTC
  4. Upsert into news_articles (dedup by url+ticker)
  5. Prune excess rows per ticker (keep newest MAX_ARTICLES_PER_TICKER)
```

### FinBERT Scoring

- Model: `ProsusAI/finbert` (loaded lazily on first use)
- Ticker-aware: prepends ticker symbol to headline before scoring
- Returns `(label, score)` per article — label is `positive`/`negative`/`neutral`, score is `[-1, 1]`
- Fallback: if torch/transformers unavailable, uses Massive `insights[]` sentiment
- Batch size 32 on 4090 → ~50ms/batch (2000 articles < 4 seconds)

### CLI

```bash
python -m data.news.ingest                  # all hot tickers
python -m data.news.ingest --tier 1         # tier-1 only (MAG7 + top ETFs)
python -m data.news.ingest --tier 2         # tier-2 only
python -m data.news.ingest --ticker NVDA    # single ticker
python -m data.news.ingest --dry-run        # fetch + score, no DB write
```

## API Endpoints

### `GET /api/news/market`

General market news. Fallback: Massive → Google RSS → Finnhub. Cached 5 min.

### `GET /api/news/hot`

DB-stored hot-ticker news (last 7 days). Falls back to API chain if DB empty. Cached 5 min.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max articles (1-200) |
| `ticker` | str | null | Filter by specific ticker |

### `GET /api/news/{ticker}`

Per-ticker news. Hot tickers → DB first → API fallback. Cold → API only (Massive → Google → Finnhub). Cached 10 min.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 7 | Lookback window (1-30) |
| `limit` | int | 20 | Max articles (1-50) |

### Unified Response Shape

All endpoints return the same article format:

```json
{
  "id": "c4902c3d-...",
  "headline": "Apple Beats Q2 Estimates",
  "summary": "Apple reported...",
  "source": "CNBC",
  "url": "https://cnbc.com/...",
  "image": "https://image.cnbc.com/...",
  "datetime": 1717848000,
  "tickers": ["AAPL"],
  "category": "general",
  "sentiment": "positive",
  "sentiment_score": 0.93
}
```

## Frontend Integration

### News Feed Page (`/news`)

- Fetches `GET /api/news/hot?limit=100` via React Query (5-min stale time)
- Falls back to `/api/news/market` if `/hot` returns empty
- **Diversified**: max `NEWS_MAX_PER_TICKER_FEED` (default 3) articles per ticker
- Ticker search: type a symbol → switches to `GET /api/news/{ticker}`
- Clickable ticker tags in articles → filters to that ticker
- Sentiment filter tabs (all/bullish/bearish/neutral)

### Signal Detail Page (`/signals/[ticker]`)

- Fetches `GET /api/news/{ticker}?days=7` via React Query
- Shows **6 articles** with per-article sentiment badges (bullish/bearish)
- **Sentiment aggregation bar** above the list (bullish/neutral/bearish proportions)
- Bar and list use the same 6-article slice for consistency

## File Structure

```
data/news/
├── __init__.py
├── constants.py      # TIER1/TIER2 tickers, intervals, limits (env-configurable)
├── ingest.py         # fetch + FinBERT score + store (Massive → Google → Finnhub)
└── scheduler.py      # lifespan thread: startup + tiered periodic

backend/app/api/routes/
└── news.py           # /market, /hot, /{ticker} (DB → API fallback chain)

ml/inference/
└── finbert_scorer.py # FinBERTScorer singleton (ProsusAI/finbert, GPU)

frontend/src/app/
├── news/page.tsx     # full news feed with search + diversification
└── signals/[ticker]/page.tsx  # 6-article news section with sentiment bar
```

## Env Vars

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MASSIVE_API_KEY` | Yes (primary) | — | Massive paid plan — news, reference, market cap |
| `MASSIVE_BASE_URL` | No | `https://api.massive.com` | Massive API endpoint |
| `FINNHUB_API_KEY` | Recommended | — | Free tier — shared with earnings, realtime WS |
| `FINNHUB_BASE_URL` | No | `https://finnhub.io/api/v1` | Finnhub API endpoint |
| `NEWS_TIER1_INTERVAL_MIN` | No | `15` | Tier-1 fetch interval (minutes) |
| `NEWS_TIER2_INTERVAL_MIN` | No | `60` | Tier-2 fetch interval (minutes) |
| `NEWS_MAX_PER_TICKER` | No | `50` | Max articles per ticker in DB |
| `NEWS_MAX_PER_TICKER_FEED` | No | `3` | Max articles per ticker on /news page |
| `NEXT_PUBLIC_NEWS_MAX_PER_TICKER_FEED` | No | `3` | Same value, exposed to Next.js |

Google News RSS needs no key. The system degrades gracefully if any source is unavailable.
