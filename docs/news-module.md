# News Module

> Last updated: 2026-06-23

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                          Data Sources                                 │
│  Massive API (PEER)        Google News RSS (PEER)   Finnhub (LAST)   │
│  - paid                    - free, no key           - FREE tier      │
│  - summary + image + tags  - near-real-time         - 60 req/min     │
│  - ticker.any_of batch     - per-ticker query       - only if both   │
│      └──── BOTH every cycle, MERGED ────┘             came back empty │
└──────────────────────────┬────────────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────────────┐
│                     FinBERT Scorer (local, GPU)                       │
│  Prepends ticker to headline: "NVDA: Intel surges..." → per-ticker   │
│  sentiment. Batch=32 on 4090 → ~50ms/batch. Falls back to Massive    │
│  insights if torch unavailable.                                      │
└──────────────────────────┬────────────────────────────────────────────┘
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
  (DB → fallback;    (DB → fallback;      (Massive → Google → Finnhub)
   ?fresh overlays    ?fresh overlays
   live market RSS)   live Google RSS)
       │                   │
       ▼                   ▼
  /news page          /signals/[ticker]
  (diversified,        (6 articles +
   max 3/ticker;        sentiment bar;
   fresh on open/       fresh on open)
   ticker search)
```

On every user entry point — opening `/news`, searching a ticker there, or opening a stock's
`/signals/[ticker]` page — the frontend passes `fresh=true`, which overlays a live Google
News RSS pull on top of the stored rows so the view is up-to-the-minute (see Frontend below).

## Source Strategy (peer sources, merged every cycle)

Massive and Google News RSS are **peers** — both are fetched and merged on **every** cycle
(not fallback-ranked). Running both is deliberate: Google alone returns too few headlines, so
the two complement each other.

- **Massive API** (paid) — the only source carrying summary text, images, and precise ticker
  tags. One batched call per 10-ticker batch (`ticker.any_of`).
- **Google News RSS** (free, no key) — near-real-time breadth (the same source the chat
  agent's `web_fetch_news` uses). One ticker-scoped query per ticker, so attribution is clean
  without headline guessing.
- **Finnhub REST** — **last resort** only, for tickers that came back empty from *both* of the
  above. Its free tier (60 req/min) is shared with the earnings calendar, realtime WebSocket
  auth, and symbol validation, so we save quota.

> **Why merge instead of fallback.** The old pipeline put Massive *first* and only fell back to
> Google when Massive returned nothing — so the free, near-real-time source was effectively
> dead code and the feed lagged the chat agent. Merging both every cycle gives full volume
> *and* freshness. Overlap is cheap: `store_articles` dedups by `(url, ticker)`, so only
> genuinely new rows are written. For up-to-the-minute reads, the API additionally overlays a
> live Google pull on demand via `?fresh=true` (see API + Frontend).

| Source | Cost | Sentiment | Summary/Image | Ticker tags | Freshness | When |
|--------|------|-----------|---------------|-------------|-----------|------|
| Massive | Paid | insights[] | Yes | `ticker.any_of` batch | Lags | Every cycle |
| Google RSS | Free | No (FinBERT computes) | No | No (per-ticker query) | Near-real-time | Every cycle |
| Finnhub | Free tier | No | summary only | Per-ticker only | Lags | Empty-only fallback |

## Fetch Tiers

| Tier | Tickers | Count | Interval | Use Case |
|------|---------|-------|----------|----------|
| **Tier-1** | MAG7 + SPY/QQQ/DIA/IWM/SOXX | 12 | Every 5 min (configurable) | Most-viewed stocks, need freshest data |
| **Tier-2** | Rest of Nasdaq-100 + key ETFs | ~81 | Every 20 min (configurable) | Broad coverage, less time-sensitive |
| **Cold** | Everything else | ∞ | On-demand | User clicks → API fetch → cache 5 min, no DB |

Tiers control **which tickers** are fetched and how often; every cycle pulls both peer
sources (Massive + Google) and merges them — see Source Strategy above.

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

1. **Startup**: full ingest of all ~93 hot tickers.
2. **Every TIER1_INTERVAL** (default 5 min): tier-1 (12 tickers).
3. **Every TIER2_INTERVAL** (default 20 min): tier-1 + tier-2 (all ~93).

Every cycle pulls **both** peer sources (Massive + Google) and merges them. Tick ratio is
computed dynamically: `tier2_every_n = round(TIER2_INTERVAL / TIER1_INTERVAL)`.

### Ingest Flow (`data/news/ingest.py`)

`ingest_tickers(..., include_massive=True)` — the scheduler always runs with both sources;
`include_massive=False` is reserved for the `--google-only` CLI / manual runs (pure Google
pass + Finnhub last-resort).

```
For each batch of 10 tickers:
  1. Google RSS: one ticker-scoped query PER ticker            # results map straight to t
     + Massive batch (ticker.any_of=NVDA,AAPL,...)             # distributed by ticker tags
     → both fetched concurrently and MERGED (peers, not fallback)
  2. Finnhub(each) — only for tickers still empty after both   # last resort, 25/min
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
python -m data.news.ingest                  # all hot tickers (Google + Massive)
python -m data.news.ingest --tier 1         # tier-1 only (MAG7 + top ETFs)
python -m data.news.ingest --tier 2         # tier-2 only
python -m data.news.ingest --ticker NVDA    # single ticker
python -m data.news.ingest --google-only    # skip Massive — pure Google RSS pass
python -m data.news.ingest --dry-run        # fetch + score, no DB write
```

## API Endpoints

All hot/company cache entries are dropped by `invalidate_news_cache()` after each ingest
cycle that wrote new rows (the scheduler runs in-process), so fresh articles are served
immediately rather than waiting for the TTL.

### `GET /api/news/market`

General market news. Fallback: Massive → Google RSS → Finnhub. Cached 2 min; also dropped
on ingest (a completed cycle means the upstream APIs have fresher headlines too, so the
next request re-pulls live).

### `GET /api/news/hot`

DB-stored hot-ticker news (last 7 days). Falls back to API chain if DB empty. Cached 2 min
(short backstop — the cache is invalidated on ingest, so this only bounds out-of-process drift).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max articles (1-200) |
| `ticker` | str | null | Filter by specific ticker |
| `fresh` | bool | false | Skip the cache and overlay a live Google News RSS pull on top of the DB result — per-ticker when `ticker` is set, market-wide otherwise. Used by the News page so opening it fetches the latest headlines. |

### `GET /api/news/{ticker}`

Per-ticker news. Hot tickers → DB first → API fallback. Cold → API only (Massive → Google → Finnhub). Cached 5 min.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 7 | Lookback window (1-30) |
| `limit` | int | 20 | Max articles (1-50) |
| `fresh` | bool | false | Overlay a live Google News RSS pull on top of DB/cached rows so the viewed ticker is as up-to-date as the chat agent. On the hot path it merges live items into the DB result (deduped by URL, DB rows keep their stored scores); on the cold path it bypasses the cache to force a live fetch. Live items are FinBERT-scored on the fly. Used by the News page for the ticker the user is actively viewing. |

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

- **On open**: fetches `GET /api/news/hot?limit=100&fresh=true` via React Query
  (60-sec stale time + `refetchOnMount: "always"`), so every visit triggers a live
  Google RSS overlay on top of the stored feed — not just whatever the last ingest cycle saved
- Falls back to `GET /api/news/market` if `/hot` returns empty
- **Diversified**: max `NEWS_MAX_PER_TICKER_FEED` (default 3) articles per ticker
- **Ticker search**: type a symbol → switches to `GET /api/news/{ticker}?fresh=true`
  (60-sec stale time + refetch on focus); the query key includes the ticker, so each search
  fires a fresh live fetch for that symbol
- Clickable ticker tags in articles → filters to that ticker
- Sentiment filter tabs (all/bullish/bearish/neutral)

#### Featured hero — image-quality gate

The market view promotes a "hero" story (1 large card + 2 small). The large card is the
only slot that renders an image, so it must not show a pixelated thumbnail:

- Candidate images are **probed client-side** for real resolution via `new window.Image()`
  (`naturalWidth`/`naturalHeight`). Only images `>= MIN_IMG_W x MIN_IMG_H` (400×200) are
  eligible; low-res or broken images are excluded.
- `scoreFeatured` awards the image bonus **only** for a validated high-res image — a low-res
  one ranks no better than no image at all.
- Hero selection prefers a story with a validated image **and** a real summary (so the large
  card isn't bare), then falls back to validated-image-only, then to text-only.
- Any low-res/broken image is stripped before render, so a sub-threshold image is never shown
  — the slot degrades to text-only or another story is featured instead.
- Feed cards guard against empty `summary` (Google-sourced rows have no summary) so there is
  no blank gap.

Since only Massive carries summaries/images (Google is headline-only), the hero naturally
lands on a Massive-sourced story (image + summary) while Google headlines keep the rest of
the feed fresh.

### Signal Detail Page (`/signals/[ticker]`)

- **On open**: fetches `GET /api/news/{ticker}?days=7&fresh=true` via React Query
  (60-sec stale time + `refetchOnMount: "always"`), so opening a stock's news fires a live
  Google RSS overlay for that ticker
- Shows **6 articles** with per-article sentiment badges (bullish/bearish)
- **Sentiment aggregation bar** above the list (bullish/neutral/bearish proportions)
- Bar and list use the same 6-article slice for consistency

## File Structure

```
data/news/
├── __init__.py
├── constants.py      # TIER1/TIER2 tickers, intervals, limits (env-configurable)
├── ingest.py         # fetch + FinBERT score + store (Massive + Google merged every cycle)
└── scheduler.py      # lifespan thread: startup + tiered periodic (both sources merged)

backend/app/api/routes/
└── news.py           # /market, /hot, /{ticker} (DB → API; ?fresh overlays live Google RSS)

ml/inference/
└── finbert_scorer.py # FinBERTScorer singleton (ProsusAI/finbert, GPU)

frontend/src/app/
├── news/page.tsx     # full news feed with search + diversification
└── signals/[ticker]/page.tsx  # 6-article news section with sentiment bar
```

## Env Vars

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MASSIVE_API_KEY` | Recommended | — | Massive paid plan — the only source of summary/image/ticker tags. Without it the pipeline runs Google-only and the feed has no summaries/images. |
| `MASSIVE_BASE_URL` | No | `https://api.massive.com` | Massive API endpoint |
| `FINNHUB_API_KEY` | Recommended | — | Free tier — shared with earnings, realtime WS |
| `FINNHUB_BASE_URL` | No | `https://finnhub.io/api/v1` | Finnhub API endpoint |
| `NEWS_TIER1_INTERVAL_MIN` | No | `5` | Tier-1 fetch interval (minutes) |
| `NEWS_TIER2_INTERVAL_MIN` | No | `20` | Tier-2 fetch interval (minutes) |
| `NEWS_MAX_PER_TICKER` | No | `50` | Max articles per ticker in DB |
| `NEWS_MAX_PER_TICKER_FEED` | No | `3` | Max articles per ticker on /news page |
| `NEXT_PUBLIC_NEWS_MAX_PER_TICKER_FEED` | No | `3` | Same value, exposed to Next.js |

Google News RSS needs no key. The system degrades gracefully if any source is unavailable.
