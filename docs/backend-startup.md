# Backend Startup, Self-Healing & Scheduled Tasks

## Overview

The PenguinAI backend is designed to recover from any restart scenario — crash, fresh deploy, or new machine — without manual intervention. The system detects missing data, auto-heals what it can, and logs clear instructions for anything that requires manual action.

---

## Startup Flow (Time-Ordered)

### Phase 1: Self-Healing Checks (~200ms, blocking)

`run_startup_checks()` runs 7 checks before any HTTP request is served:

| # | Check | Level | Auto-Heal? | Details |
|---|-------|-------|------------|---------|
| 1 | DB connection | BLOCKING | No | `SELECT 1` — fatal if PostgreSQL unreachable |
| 2 | Schema exists | BLOCKING | No | Verifies 8 critical tables in `pg_tables`/`pg_views`. Fails with "run `make db-init`" |
| 3 | Tickers populated | BLOCKING | **Yes** | If `tickers` table empty → bootstraps 36 core tickers from `scripts/bootstrap_universe.py` |
| 4 | Admin user | BLOCKING | **Yes** | If no ADMIN tier user exists → creates one from `ADMIN_EMAIL`/`ADMIN_PASSWORD` env vars |
| 5 | Redis connectivity | NON-BLOCKING | No | Warns if Redis down (rate limiting + Celery dispatch degraded) |
| 6 | Signal cache fresh | NON-BLOCKING | **Yes** | If stale/empty → dispatches `refresh_top100` Celery task to Redis queue |
| 7 | bars_30m data | NON-BLOCKING | No | `SELECT 1 FROM bars_30m LIMIT 1` — logs "run `make import-30min`" if empty |
| 8 | market_data_1min | NON-BLOCKING | No | `SELECT max(time)` — informational; realtime supervisor will populate |

**BLOCKING** checks short-circuit on failure — server refuses to start.
**NON-BLOCKING** checks log warnings and continue in degraded mode.

**Code:** `backend/app/core/startup.py`

### Phase 2: Realtime Supervisor (immediate)

`_SupervisorWatchdog` spawns a subprocess running `data.ingestion.realtime.supervisor`:

```
Watchdog (main process thread)
  └── Subprocess: realtime supervisor
        ├── IBKR WebSocket (50 core symbols, sub-second latency)
        ├── Finnhub WebSocket (same 50 symbols, ~150ms latency)
        └── CrossValidator (30s interval, price divergence detection)
              → writes to market_data_1min (ON CONFLICT upsert)
```

**Self-healing:**
- Crash → exponential backoff restart (1s, 2s, 4s, ..., max 60s)
- 10 crashes in 1 hour → gives up, logs CRITICAL
- Stable for 1 hour → crash counter resets
- `REALTIME_ENABLED=false` disables entirely

**Code:** `backend/app/main.py` (`_SupervisorWatchdog` class)

### Phase 3: Background Data Threads (immediate, non-blocking)

Five daemon threads start simultaneously. Each fetches data immediately on startup, then on a schedule:

| Thread | Startup Action | Schedule | Data Source | Target Table |
|--------|---------------|----------|-------------|--------------|
| `celeb-fetch` | Fetch immediately | Daily 19:00 ET (weekdays) | SEC EDGAR, Quiver, arkfunds.io | `celebrity_holdings` |
| `mcap-fetch` | Fetch immediately | Daily 06:00 ET (weekdays) | Massive API | `tickers.market_cap` |
| `earnings-sched` | Fetch immediately | 08:00 + 18:00 ET (weekdays) | Finnhub API | `earnings` |
| `news-sched` | Fetch immediately | Tier-1: 15min, Tier-2: 60min | Massive API | `news_articles` |
| `seed-data` | Check & seed | Once (then exits) | Local parquets or Massive API | `bars_30m`, `bars_1d`, `instruments` |

**Error handling:** Each thread has independent `try/except` — one thread's failure doesn't affect others. Missing dependencies (`ImportError`) are caught and logged.

### Phase 4: Service Ready

FastAPI begins accepting HTTP requests. The `/health` endpoint reports full status.

### Phase 5: Graceful Shutdown

On SIGTERM, threads are stopped in reverse order with 5-second join timeouts:

```
seed_stop.set()     → seed_thread.join(5s)
news_stop.set()     → news_thread.join(5s)
earnings_stop.set() → earnings_thread.join(5s)
mcap_stop.set()     → mcap_thread.join(5s)
celeb_stop.set()    → celeb_thread.join(5s)
watchdog.stop()     → SIGTERM subprocess → wait 10s → SIGKILL
```

---

## Market Data Auto-Seed

On a from-zero startup, the `seed-data` thread automatically populates critical market data so charts aren't blank.

**Code:** `backend/app/core/seed_market_data.py`

### Decision Flow

```
DB has bars for seed tickers? ──→ YES → skip (normal restart, <10ms)
    │ NO
    ▼
Local parquet files exist?
  data/30min_data/{stock,etf}/AAPL.parquet etc.
  data/daily_data/{stock,etf}/AAPL.parquet etc.
    │ YES → import from parquets (includes indicators, ~10-30s)
    │ NO
    ▼
MASSIVE_API_KEY configured?
    │ YES → fetch from Massive API (~1-3 min)
    │         30m bars: last 30 days × all seed tickers
    │         Daily bars: last ~400 days × all seed tickers
    │         OHLCV only (no indicators — charts work, ML stays NEUTRAL)
    │ NO → log warning, exit
```

### Seed Tickers

Derived from `scripts/bootstrap_universe.py` (single source of truth). Currently 36 tickers: MAG7, top semiconductors, financials, healthcare, energy, retail, and key ETFs.

### Per-Ticker Commit

Each ticker commits independently. If ticker 16 fails, tickers 1-15 are preserved.

### Thread Safety

The seed creates its own `asyncpg` engine + session factory via `_make_session()` because it runs in a background thread with its own asyncio event loop. It does NOT reuse the main thread's `AsyncSessionLocal`.

---

## Health Endpoint

```
GET /health
```

Returns comprehensive status:

```json
{
  "status": "ok | degraded | failed",
  "version": "0.1.0",
  "realtime": {
    "supervisor": "running | dead | disabled",
    "pid": 12345,
    "restarts": 0,
    "services": { ... }
  },
  "data_readiness": {
    "db_connection": { "status": "ok", "message": "PostgreSQL connected" },
    "schema": { "status": "ok", "message": "All 8 critical tables present" },
    "tickers": { "status": "ok", "detail": { "count": 36 } },
    "redis": { "status": "ok", "message": "Redis connected" },
    "signal_cache": { "status": "ok", "detail": { "total": 100, "fresh": 95 } },
    "bars_30m": { "status": "ok", "detail": { "bars_30m_has_data": true } },
    "market_data_1min": { "status": "ok", "detail": { "latest": "2026-06-09T20:01:00+00:00" } }
  },
  "startup": {
    "completed_at": "2026-06-09T06:30:01.234567+00:00",
    "overall": "ok"
  }
}
```

**Note:** `data_readiness` is a snapshot from startup time. It does not refresh on each request.

---

## Scheduled Tasks (Celery Beat)

These run in separate containers (`celery_worker`, `ml_worker`, `celery_beat`):

### ML Inference Queue (GPU worker)

| Task | Schedule | What It Does |
|------|----------|-------------|
| `refresh_top100` | Hourly, 9am-5pm ET weekdays | Re-run ML + sentiment + LLM → update `signal_cache` (1h TTL) |
| `daily_pipeline` | 10pm ET weekdays | Retrain XGBoost + RF models → update Top-100 Redis list |

### Default Queue (CPU worker)

| Task | Schedule | What It Does |
|------|----------|-------------|
| `scrape_social` | Every 30 min | Reddit + Twitter → FinBERT → `social_posts` |
| `refresh_hot_news` | :15 and :45 each hour | Nasdaq-100 news → `news_articles` |
| `fetch_fundamentals` | 8am ET weekdays | **Stub — not yet implemented** |
| `validate_symbols` | Every 6h at :30 | Validate user-requested symbols via Massive API |

---

## From-Zero Startup Timeline

```
T=0s      docker-compose up
          ├── TimescaleDB starts, applies db/schema/*.sql (first run only)
          ├── Redis starts
          └── Healthchecks pass (~30s)

T=30s     API container starts → lifespan() begins
          ├── ✅ DB connected
          ├── ✅ Schema: 8 tables present
          ├── 🔧 tickers: bootstrapped 36 tickers (was empty)
          ├── 🔧 admin: created admin user
          ├── ⚠️ Redis: connected
          ├── 🔧 signal_cache: dispatched refresh_top100
          ├── ⚠️ bars_30m: empty
          └── ⚠️ market_data_1min: empty

T=31s     Service ready — accepting requests
          Background threads start:
          ├── seed: checking parquets / Massive API
          ├── market_cap: fetching from Massive
          ├── earnings: fetching from Finnhub
          ├── celebrity: fetching SEC/Congress/ARK
          ├── news: fetching from Massive
          └── realtime supervisor: connecting IBKR + Finnhub WS

T=1-3min  Seed complete → charts available for 36 tickers
          Market cap complete → Heatmap available
          Earnings complete → Earnings page available
          Celebrity holdings complete
          News complete

T=5min    ML worker processes refresh_top100
          └── Dashboard shows signals (NEUTRAL if no indicators, real if parquets imported)

T=10pm    daily_pipeline retrains models (if bars_30m has data)

T=next AM First hourly refresh with trained models
          └── Dashboard shows real ML-powered signals
```

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/core/startup.py` | Startup health checks + auto-healing |
| `backend/app/core/seed_market_data.py` | Auto-seed critical market data |
| `backend/app/main.py` | Lifespan orchestrator, watchdog, background threads |
| `backend/app/core/database.py` | Async engine + session factory (main thread only) |
| `backend/app/core/config.py` | Settings (DATABASE_URL, REDIS_URL, MASSIVE_API_KEY, etc.) |
| `scripts/bootstrap_universe.py` | Canonical ticker list (36 tickers) |
| `ml/tasks/celery_app.py` | Celery beat schedule |
| `ml/tasks/hourly_signal_cache.py` | Top-100 signal refresh task |
| `data/ingestion/realtime/supervisor.py` | IBKR + Finnhub WebSocket supervisor |

---

## Environment Variables for Self-Healing

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis for Celery + rate limiting |
| `MASSIVE_API_KEY` | No | Enables auto-seed from Massive API when no parquets exist |
| `MASSIVE_BASE_URL` | No | Default: `https://api.massive.com` |
| `FINNHUB_API_KEY` | No | Enables earnings auto-fetch |
| `ADMIN_EMAIL` | No | Auto-create admin user on startup |
| `ADMIN_PASSWORD` | No | Password for auto-created admin (auto-generated if not set) |
| `REALTIME_ENABLED` | No | Default: `true`. Set to `false` to disable realtime supervisor |
