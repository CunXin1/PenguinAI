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
│  finbert_score for NVDA vs INTC. Auto-pruned at 90 days.            │
└──────────────────────────┬────────────────────────────────────────────┘
                           │
       ┌───────────────────┼──────────────────┐
       ▼                   ▼                  ▼
  /api/news/hot      /api/news/{ticker}   /api/news/market
  (DB → fallback)    (DB → fallback)      (Massive → Google → Finnhub)
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
| **Tier-1** | MAG7 + SPY/QQQ/DIA/IWM/SOXX | 12 | Every 15 min | Most-viewed stocks, need freshest data |
| **Tier-2** | Rest of Nasdaq-100 + key ETFs | ~81 | Every 60 min | Broad coverage, less time-sensitive |
| **Cold** | Everything else | ∞ | On-demand | User clicks → API fetch → cache 10 min, no DB |

Tier definitions: `data/news/constants.py`

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
- `(url)` — dedup lookups
- `(url, ticker)` — per-ticker dedup
- `(ticker, finbert_label)` partial — sentiment aggregation

## Ingestion Pipeline

### Scheduler (`data/news/scheduler.py`)

Runs as a backend lifespan thread (same pattern as earnings, celebrity holdings):
1. **Startup**: full ingest of all ~93 hot tickers
2. **Every 15 min**: tier-1 (12 tickers)
3. **Every 60 min**: tier-1 + tier-2 (all 93)

### Ingest Flow (`data/news/ingest.py`)

```
For each batch of 10 tickers:
  1. fetch_massive(batch, limit=50)          # ticker.any_of=NVDA,AAPL,...
     └─ if empty → fetch_google_rss(batch)   # free fallback
        └─ if empty → fetch_finnhub(each)    # last resort, rate-limited 25/min
  2. Distribute articles to tickers they mention
  3. FinBERT score each headline per ticker:
     "NVDA: Intel Surges on Google Foundry Order" → negative for NVDA
     "INTC: Intel Surges on Google Foundry Order" → positive for INTC
  4. Upsert into news_articles (dedup by url+ticker)
```

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

DB-stored hot-ticker news. Falls back to API chain if DB empty. Cached 5 min.

### `GET /api/news/{ticker}`

Per-ticker news. Hot tickers → DB first → API fallback. Cold → API only. Cached 10 min.

### Unified Response

```json
{
  "id": "c4902c3d-...",
  "headline": "Apple Beats Q2 Estimates",
  "summary": "...",
  "source": "CNBC",
  "url": "https://...",
  "image": "https://...",
  "datetime": 1717848000,
  "tickers": ["AAPL"],
  "category": "general",
  "sentiment": "positive",
  "sentiment_score": 0.93
}
```

## File Structure

```
data/news/
├── __init__.py
├── constants.py      # TIER1/TIER2 tickers, intervals (single source of truth)
├── ingest.py         # fetch + FinBERT score + store (Massive → Google → Finnhub)
└── scheduler.py      # lifespan thread: startup + tiered periodic

backend/app/api/routes/
└── news.py           # /market, /hot, /{ticker} (DB → API fallback chain)

ml/inference/
└── finbert_scorer.py # FinBERTScorer singleton (ProsusAI/finbert, GPU)
```

## Env Vars

| Variable | Required | Description |
|----------|----------|-------------|
| `MASSIVE_API_KEY` | Yes (primary) | Massive paid plan — news, reference, market cap |
| `MASSIVE_BASE_URL` | No | Default `https://api.massive.com` |
| `FINNHUB_API_KEY` | Recommended | Free tier — shared with earnings, realtime WS |
| `FINNHUB_BASE_URL` | No | Default `https://finnhub.io/api/v1` |

Google News RSS needs no key. The system degrades gracefully if any source is unavailable.
