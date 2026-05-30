# PenguinAI — CLAUDE.md

AI-automated US stock investment signal recommendation system.
Signals only — no trading execution. Public SaaS product.

## Architecture

Three independent layers, never mix concerns:

```
frontend/   → Next.js 15 (React + TypeScript)     port 3000
backend/    → FastAPI (API Gateway)                port 8000
ml/         → ML inference + Celery workers        GPU (4090)
data/       → Data ingestion + scrapers
db/schema/  → TimescaleDB + pgvector SQL
```

## Database

**TimescaleDB** is the primary store. Two categories:

| Table | Purpose |
|-------|---------|
| `market_data_30min` | Historical 30-min bars (2000–present, ~170M rows) — PRIMARY training source |
| `market_data_1min`  | Real-time IBKR stream, accumulates forward from today |
| `market_data_daily` | Daily bars for macro context |
| `indicators_30min`  | Pre-computed technical indicators aligned to 30-min bars |
| `social_posts`      | Twitter VIPs + Reddit WSB, FinBERT-scored, pgvector-embedded |
| `signal_cache`      | Computed signals with TTL (Top-100: 1h, cold: 4h) |
| `users`             | Auth + tier (FREE/PRO/PREMIUM/ADMIN) |
| `watchlists`        | User → ticker many-to-many |
| `celebrity_holdings`| 13F + daily disclosure filings |
| `earnings`          | EPS actual/estimate/surprise |
| `fundamentals`      | PE ratio, market cap daily snapshot |
| `fomc_statements`   | Hawk/dove scores, global macro filter |

DuckDB is used ONLY for local ML feature engineering (reads Parquet exports). Never write user or live data to DuckDB.

## Signal Generation Pipeline

```
30-min bars → technical features → XGBoost + RF → FinBERT sentiment →
RAG (pgvector, ticker+time filtered) → Gemma 4 Agent 1 (assemble) →
Gemma 4 Agent 2 (reason, JSON mode locked) → FOMC filter → signal_cache
```

**Critical:** Gemma 4 prompts are 100% backend-assembled. Zero user free-text input anywhere. No prompt injection surface.

## Caching (dual-track)

- **Top-100** (NVDA, AAPL, BTC, etc.): pre-computed hourly by Celery Beat → instant response
- **Cold tickers**: on-demand Celery task (~2–5s) → cached 4h after first hit
- Frontend: 202 response = polling mode (real loading animation), cached = instant

## Signal Output Contract

```python
{
    "ticker": str,
    "direction": "LONG" | "SHORT" | "NEUTRAL",
    "confidence": float,          # 0.0–1.0
    "holding_period": "INTRADAY" | "SHORT_TERM" | "SWING" | "POSITION",
    "ml_scores": { xgb_prob_up, rf_prob_up, ensemble_prob },
    "sentiment": { finbert_score, post_count, hawk_dove_ref },
    "ai_attribution": str,        # ≤150 chars, key drivers
    "ai_analysis": str,           # ≤300 chars, professional summary
    "tier_required": "FREE" | "PRO" | "PREMIUM",
}
```

Do not change this schema without updating `signal_cache` table, `schemas/signal.py`, and `frontend/src/lib/types.ts` together.

## ML Models

- XGBoost: primary classifier. GPU training (`device="cuda"`). TimeSeriesSplit CV (no leakage).
- RandomForest: secondary, ensemble diversity. `class_weight="balanced"`.
- Feature names are the single source of truth in `ml/models/xgboost_trainer.py:FEATURE_COLS`.
- Models saved as pickle at `/models/penguinai/xgboost_prod.pkl` and `rf_prod.pkl`.
- Hot-reload via `model_registry.reload()` — no restart needed after retraining.
- Target horizon: 16 × 30-min bars = 8 hours ahead (adjustable in trainer).

## User Tiers

```
FREE     → basic signals (top 100, daily refresh)
PRO      → full 2000 stocks, real-time signals
PREMIUM  → API key access (future), LLM chat (future, not in MVP)
ADMIN    → internal monitoring, pipeline control
```

Tier check is done in `backend/app/api/deps.py:require_tier()`. Signal rows carry `tier_required` field.

## Celery Schedule

| Task | Schedule | Queue |
|------|----------|-------|
| `refresh_top100` | Hourly 9am–5pm ET weekdays | ml_inference |
| `run_daily_pipeline` | 10pm ET weekdays | ml_inference |
| `scrape_social_media` | Every 30 min | default |
| `fetch_fundamentals` | 8am ET weekdays | default |

## Data Sources

| Source | What | How |
|--------|------|-----|
| User's own data | 30-min bars 2000–present (full market) | Import script TBD |
| IBKR WebSocket | Real-time 1-min bars during market hours | `data/ingestion/ibkr_stream.py` |
| Polygon.io | Historical minute bars (supplemental) | `data/ingestion/polygon_loader.py` |
| Twitter/X | VIP finance accounts | `data/scrapers/twitter_scraper.py` (Playwright) |
| Reddit | r/wallstreetbets + r/stocks | `data/scrapers/reddit_scraper.py` (PRAW) |
| SEC EDGAR | 13F filings + FOMC statements | `data/scrapers/sec_scraper.py` |

## Frontend Rules

- **Dark theme only.** Background: zinc-950 (`#09090b`). Never use white backgrounds.
- LONG signals: emerald green. SHORT signals: red. NEUTRAL: zinc gray.
- Signal confidence shown as a progress bar, not just a number.
- TradingView Lightweight Charts for all candlestick charts (package: `lightweight-charts`).
- API calls via `frontend/src/lib/api.ts` only — never fetch directly from components.
- Types live in `frontend/src/lib/types.ts`. Keep in sync with backend Pydantic schemas.

## Development Workflow

```bash
# Start full stack locally
docker-compose up

# Backend only (fast iteration)
cd backend && uvicorn app.main:app --reload

# ML worker (requires GPU)
cd ml && celery -A ml.tasks.celery_app worker --queues=ml_inference -c 1

# Frontend
cd frontend && npm run dev

# Bootstrap ticker universe (run once)
python scripts/bootstrap_universe.py
```

## What NOT to do

- Do not add LangChain or any LLM orchestration framework. Everything is native Python async.
- Do not allow any user-provided free text to reach the LLM. All prompts are backend-assembled.
- Do not write trading/order execution code. Signals only.
- Do not use Streamlit for the user-facing product. Streamlit is for internal ML monitoring only.
- Do not run ML training inside the FastAPI process. Always dispatch to Celery ml_inference queue.
- Do not store raw API keys in code. All secrets via `.env` / environment variables.
