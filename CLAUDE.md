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
| `bars_30m` | Historical 30-min bars + inline indicators (2000–present, ~236M rows) — PRIMARY 30-min store, loaded from `data/30min_data` parquet |
| `bars_1d` | Daily bars + indicators + multi-horizon returns (from `data/daily_data`) |
| `instruments` | symbol ↔ instrument_id dimension (bars_* FK here) |
| `market_data_30min` *(view)* | adj OHLCV over `bars_30m` — compat name for app/ML |
| `market_data_daily` *(view)* | adj OHLCV over `bars_1d` — compat name for macro context |
| `indicators_30min` *(view)* | model-ready features over `bars_30m` (matches `FEATURE_COLS`) |
| `market_data_1min`  | Real-time dual-source (IBKR + Finnhub) + Massive minute stream, accumulates forward from today (real table) |
| `social_posts`      | Twitter VIPs + Reddit WSB, FinBERT-scored, pgvector-embedded |
| `signal_cache`      | Computed signals with TTL (Top-100: 1h, cold: 4h) |
| `users`             | Auth + tier (FREE/PRO/PREMIUM/ADMIN) |
| `watchlists`        | User → ticker many-to-many |
| `pinned_signals`    | User-customizable Top Signals ticker list (0–12, ordered by position) |
| `chat_conversations` / `chat_messages` | LLM Chat Agent per-user history (conversations + messages, cascade-delete) — see "LLM Chat Agent" |
| `celebrity_holdings`| Smart money trades: SEC 13F (Buffett/Soros/Dalio/Ackman), ARK (Cathie Wood), Congress (Pelosi/Tuberville/MTG/Crenshaw), Trump DJT (13D) — auto-refreshed daily |
| `news_articles`     | Per-ticker FinBERT-scored headlines (hypertable, one row per article×ticker, 90-day retention, max 50/ticker) — auto-populated by `data/news/scheduler.py` |
| `earnings`          | EPS actual/estimate/surprise |
| `fundamentals`      | PE ratio, market cap daily snapshot |
| `fomc_statements`   | Hawk/dove scores, global macro filter |

DuckDB is used ONLY for local ML feature engineering (reads Parquet exports). Never write user or live data to DuckDB.

**Train/serve parity:** training reads the `data/30min_data` parquet via DuckDB; serving reads the `indicators_30min` view. Both derive features through the *same* SQL — `xgboost_trainer.FEATURE_SQL` mirrors `04_compat_views.sql:indicators_30min` — so there is no train/serve skew. Load the parquet into `bars_30m`/`bars_1d` with `make import-30min` (after `make db-init`).

## Signal Generation Pipeline

```
30-min bars → technical features → XGBoost + RF → FinBERT sentiment →
RAG (pgvector, ticker+time filtered) → Gemma 4 Agent 1 (assemble) →
Gemma 4 Agent 2 (reason, JSON mode locked) → FOMC filter → signal_cache
```

**Critical:** In the *signal pipeline*, Gemma 4 prompts are 100% backend-assembled —
zero user free-text, no prompt-injection surface. This invariant is scoped to the
signal pipeline. The separate **LLM Chat Agent** (below) DOES take user input and has
its own security model — never conflate the two surfaces.

## LLM Chat Agent (PREMIUM) — built

A SECOND, separate LLM surface from the signal pipeline: conversational, tool-calling,
per-user, with persisted history and SSE token streaming. It shares the backend layer
(`ml/inference/llm/`) but nothing else — keep the two harnesses separate. Unlike the
signal pipeline, it intentionally accepts user free text, so it carries its own
(non-negotiable) security model. **Full reference: `docs/llm-chat-agent.md`.**

Built end-to-end: per-user `chat_conversations` / `chat_messages` tables, conversation
CRUD + streaming send endpoints (`/api/chat/conversations*`), the `ChatAgent` tool loop
(`ml/inference/chat/`), and a server-backed chat UI (`frontend/src/app/chat/page.tsx`).

**Tools (READ-ONLY).** The model requests a tool; the backend executes the handler and
feeds the result back — multi-turn loop until a final answer.

| Tool | Backs onto | Status |
|------|-----------|--------|
| `get_watchlist(user)` | `watchlists` | built |
| `get_quote` / `get_history(ticker, range)` | `market_data_30min` / `market_data_daily` | built |
| `get_indicators(ticker)` | `indicators_30min` view | built |
| `get_earnings(ticker)` | `earnings` | built |
| `get_fundamentals(ticker)` | `fundamentals` | built |
| `get_news(ticker)` | `news_articles` (incl. Google News RSS) | built |
| `get_portfolio(user)` | portfolio table | **NOT built** — needs new `portfolio`/`positions` table + ingestion |
| `web_search(query)` | external search API | **NOT built** — needs a search provider |
| `get_signal(ticker)` | `signal_cache` (ML scores) | **TODO** — let the agent explain bull/bear from the ML models (see `docs/roadmap.md` A4) |

**Backend (go-forward LLM strategy).** Transport is swappable via `LLM_BACKEND`
(`auto` → Ollama on macOS, vLLM on Linux/Windows GPU, or `api`). Tool calling AND token
streaming are implemented on **both Ollama and vLLM** (`chat_tools` + `chat_tools_stream`);
the hosted API backend degrades to non-streamed. NOTE: Ollama's Gemma 4 tool-call parser
works reliably as of Ollama 0.22.1 — the earlier "must use vLLM" caveat is obsolete. Two
Gemma-4 gotchas, both handled: send `"think": false` (else the reasoning phase empties
the output), and Ollama needs object (not JSON-string) tool-call `arguments` on replay
(`OllamaBackend._to_ollama_msg` normalizes).

**Security (this is a NEW attack surface — all mandatory):**
- `user_id` is ALWAYS injected server-side from the auth token, **never** from the model.
  A user can never reach another user's holdings/watchlist, even via prompt injection.
  (Verified: cross-user conversation access returns 404.)
- Tools are **read-only**. No order execution, no writes, no destructive actions (Signals only).
- External content (news, search results) is **untrusted data, never instructions** — sandbox it.
- Tool args are whitelisted/validated before execution. Metered per user (Redis quota).

**Roadmap:** rich in-chat cards (inline charts/watchlist/news links), ML-backed
bull/bear explanation, and a "should I buy X?" multi-tool synthesis — see `docs/roadmap.md`.

## Caching (dual-track)

- **Top-100** (NVDA, AAPL, BTC, etc.): pre-computed hourly by Celery Beat → instant response
- **Cold tickers**: on-demand Celery task (~2–5s) → cached 4h after first hit
- Frontend: 202 response = polling mode (real loading animation), cached = instant

## Pinned Signals (Top Signals customization)

Users choose which tickers appear in the dashboard "Top Signals" section (0–12 tickers).

**Dual-track storage** (same pattern as watchlist):
- **Guest**: `localStorage` key `penguinai_pinned_signals`, JSON array of ticker strings
- **Logged-in**: `pinned_signals` table (user_id, ticker, position), accessed via REST API

**Default 9**: AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, SPY, QQQ

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/pinned-signals` | Bearer | Return ordered ticker list |
| PUT | `/api/pinned-signals` | Bearer | Replace entire list (body: `{tickers: string[]}`, max 12, validates each ticker exists) |

### Key Files

```
db/schema/03_relational.sql              — pinned_signals table DDL
backend/app/models/pinned_signal.py      — SQLAlchemy model
backend/app/api/routes/pinned_signals.py — GET + PUT endpoints
frontend/src/hooks/usePinnedSignals.ts   — guest/server dual-track hook (add, remove, has, isFull)
frontend/src/hooks/useTopSignals.ts      — accepts optional pinnedTickers filter
frontend/src/components/dashboard/TopSignals.tsx — edit UI (pencil toggle, ✕ remove, + add with validation)
```

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

Full reference: `docs/ml-specialization.md`. Roadmap context: `docs/roadmap.md` B1/B2.

- XGBoost: primary classifier. GPU training (`device="cuda"`). RandomForest: secondary,
  ensemble diversity (`class_weight="balanced"`). XGB beats RF throughout.
- **CV is purged walk-forward, NOT `TimeSeriesSplit`.** `purged_walk_forward_splits`
  (`xgboost_trainer.py`) globally time-sorts the pooled rows and embargoes overlapping
  labels (`label_end_ts = LEAD(ts, horizon)`); the old `TimeSeriesSplit` leaked on both.
  Honest leakage-free AUC for short-horizon *direction* is ~0.50 — mega-cap 1-week
  up/down is near-random; that is real, not a bug. Do not reintroduce `TimeSeriesSplit`.
- Feature names: 30m models use `xgboost_trainer.py:FEATURE_COLS` (parity with
  `indicators_30min`); 1d models use `DAILY_FEATURE_SQL`. Each saved model carries its own
  `feature_names_in_` — read that at serve time rather than assuming the global list.
- `load_training_data(timeframe, target_type)`: `timeframe` ∈ {`30m`→`data/30min_data`,
  `1d`→`data/daily_data`}; `target_type` ∈ {`direction`, `beat_spy` (excess return vs SPY,
  joins SPY forward returns — use for multi-month horizons so the model isn't "always up")}.
- **Two model families now coexist:**
  - Global: `xgboost_prod.pkl` / `rf_prod.pkl` (current signal pipeline + `model_registry`).
  - **Per-basket × horizon** (B1/B2, built): a *basket* is a curated ticker list
    (`ml/models/baskets.py`; `nasdaq10` now, `smallcap`/`wholemarket` planned) — pooled
    per basket (single-stock models were rejected: overfit). Keyed
    `{basket}__{timeframe}__{label}__{algo}.pkl`. Built: 1w (30m, direction), 1m/3m (1d,
    beat_spy). 1-day deferred until 1-min / aggregated-10-min data lands. Train:
    `python -m ml.scripts.train_basket_models`.
- Hot-reload via `model_registry.reload()`. Models saved under `MODEL_DIR`.
- **Known issue + go-forward (B-synthesis):** Top-Signal confidences cluster at ~50%
  because the single global model's `ensemble_prob` itself clusters at 0.5 (stddev ~0.07).
  The leakage fix does NOT decluster this (it is honest). The fix is to feed the keyed
  horizon models into `signal_engine`/`gemma_agent` and have Gemma synthesize all horizons
  + news/FinBERT + indicators + price/volume + earnings + macro into ONE signal, with
  confidence = cross-source/cross-horizon agreement (NOT a single near-0.5 probability).
  Never inflate confidence artificially. (Gemma-framework changes are owned elsewhere.)

## User Tiers

```
FREE     → basic signals (top 100, daily refresh)
PRO      → full 2000 stocks, real-time signals
PREMIUM  → API key access (future), LLM chat agent (tool-calling, building — see "LLM Chat Agent")
ADMIN    → internal monitoring, pipeline control
```

Tier check is done in `backend/app/api/deps.py:require_tier()`. Signal rows carry `tier_required` field.

## Authentication

### Endpoints

| Method | Path | Auth | Rate Limit | Purpose |
|--------|------|------|------------|---------|
| POST | `/api/auth/register` | — | 5/hr per IP | Create account + send verify email; **no JWT** (hard verification) |
| POST | `/api/auth/login` | — | 10/min per IP + 20/hr per account | Authenticate, return JWT; **403 `email_not_verified`** if unverified |
| GET | `/api/auth/me` | Bearer | — | Current user profile (rejects unverified tokens) |
| POST | `/api/auth/verify-email` | — | — | Verify email with token |
| POST | `/api/auth/resend-verification` | — | 5/hr per IP | Resend verify email (public, body `{email}`, anti-enumeration) |
| POST | `/api/auth/forgot-password` | — | 5/hr per IP | Request password reset |
| POST | `/api/auth/reset-password` | — | 5/hr per IP | Reset password with token |
| POST | `/api/auth/change-password` | Bearer | — | Change password (returns new JWT) |
| GET | `/api/auth/oauth/{provider}` | — | — | Start Google/Apple OAuth (302 to provider) |
| GET·POST | `/api/auth/oauth/{provider}/callback` | — | — | OAuth callback → find-or-create user, issue JWT, 302 to frontend `/auth/callback` |

All rate limits configurable via `.env` (`RATE_LIMIT_*` vars). Redis-backed; falls through when Redis is down.

### Registration Flow

```
Frontend (register form) → POST /register
  → Pydantic validates (email, username [3-20 [a-z0-9_], required+unique], password strength, display_name ≤50)
  → email.lower() normalized; username uniqueness checked case-insensitively
  → check duplicate → INSERT users (email_verified=false, token_version=0)
  → generate verify token (JWT, purpose=verify, 24h expiry)
  → send verification email (EMAIL_BACKEND=console logs it; =smtp delivers it; token also in DEBUG response)
  → return { message, email }  — NO JWT issued (hard verification)
  → Frontend stashes email in sessionStorage → redirect /auth/verify-pending
```

**Hard email verification (mandatory gate):** an account exists in `users` before
verification (so the verify link can find it) but cannot be *used* until verified:
- `register` issues no token.
- `login` returns 403 `{code: "email_not_verified", email}` for unverified accounts.
- `get_current_user` (deps.py) rejects any token whose user is unverified (401).
- `resend-verification` is public (body `{email}`), rate-limited, anti-enumeration.
- OAuth users are pre-verified by the provider, so they pass the gate normally.

### Email Verification Flow

```
User clicks email link → /auth/verify-email?token=xxx
  → POST /verify-email { token }
  → decode JWT (purpose=verify) → lookup user by email
  → set email_verified=true
  → Frontend shows success → redirect to /auth/login
```

### Login Flow

```
Frontend (login form) → POST /login
  → IP rate limit (10/min) + account rate limit (20/hr, keyed by email SHA256)
  → identifier (email OR username) → SELECT user WHERE (lower(email)=id OR lower(username)=id) AND is_active=true
  → bcrypt verify (DUMMY_HASH if user not found — constant-time)
  → if not email_verified → 403 { code: "email_not_verified", email } (frontend routes to /auth/verify-pending)
  → return JWT with { sub: user_id, ver: token_version }
```

### Password Reset Flow

```
/auth/forgot-password → POST /forgot-password { email }
  → always returns same message (no email enumeration)
  → if user exists: generate reset token (JWT, purpose=reset, 1h expiry)

User clicks email link → /auth/reset-password?token=xxx
  → POST /reset-password { token, password }
  → decode JWT → lookup user → update password_hash → token_version += 1
  → all existing sessions immediately invalidated
```

### Change Password Flow

```
POST /change-password { current_password, new_password } (requires Bearer)
  → verify current password → update password_hash → token_version += 1
  → return new JWT with updated ver claim
  → all other sessions immediately invalidated
```

### Security Measures

- **Password:** bcrypt hash, strength validation (8+ chars, upper, lower, digit, special)
- **JWT:** HS256, 7-day expiry, `ver` claim tied to `users.token_version`
- **Token revocation:** `token_version` incremented on password change/reset → old JWTs rejected
- **Rate limiting:** dual-layer (per IP via Redis INCR + per account via email SHA256 hash)
- **Timing attack prevention:** bcrypt always runs against DUMMY_HASH when user not found
- **Email normalization:** `.lower()` at all entry points (register, login, forgot-password)
- **SECRET_KEY:** auto-generates ephemeral key if insecure; CRITICAL log in non-DEBUG mode
- **Email verification (enforced):** JWT token, 24h expiry, `email_verified` column. Hard gate — unverified accounts cannot log in or hold a usable token (see Registration Flow). `EMAIL_BACKEND=console|smtp` (default console logs the link; set smtp + `SMTP_*` to actually deliver).

### Key Files

```
backend/app/api/routes/auth.py     — all auth endpoints
backend/app/api/deps.py            — get_current_user, require_tier, token_version check
backend/app/core/security.py       — bcrypt, JWT create/decode (access, reset, verify)
backend/app/core/rate_limit.py     — Redis rate limiter + account-level limiter
backend/app/core/config.py         — SECRET_KEY validation, RATE_LIMIT_* settings
backend/app/schemas/user.py        — Pydantic request/response models
backend/app/models/user.py         — SQLAlchemy User model
frontend/src/app/auth/login/       — login + register (tab toggle)
frontend/src/app/auth/verify-pending/ — post-registration "check your email"
frontend/src/app/auth/verify-email/   — token verification landing page
frontend/src/app/auth/forgot-password/ — request password reset
frontend/src/app/auth/reset-password/  — set new password with token
frontend/src/hooks/useAuth.ts      — client-side auth state (token + /me query)
frontend/src/lib/api.ts            — auth API client methods
```

### Admin Dashboard Key Files

```
backend/app/api/routes/admin/      — admin API sub-package (health, db, tasks, datasources, models, users, actions, logs)
backend/app/schemas/admin.py       — Pydantic response models for all admin endpoints
backend/app/core/utils.py          — human_size() shared utility (used by database.py + models.py)
backend/app/core/startup.py        — check_and_seed_admin() creates ADMIN user on first startup
ml/tasks/celery_app.py             — Celery task signal handlers (task_prerun/success/failure → Redis)
frontend/src/app/admin/page.tsx    — admin dashboard page (ADMIN-only gate + 9 panel layout)
frontend/src/components/admin/     — 10 admin panel components (HealthOverview, DatabaseHealth, etc.)
frontend/src/app/auth/login/       — ADMIN login auto-redirects to /admin
docs/admin-dashboard.md            — full admin dashboard documentation (中文)
```

**Admin account**: Auto-seeded on startup. Configure via `.env`: `ADMIN_EMAIL` + `ADMIN_PASSWORD` (empty = random, printed to log). Password synced from `.env` on every startup.

## Celery Schedule

| Task | Schedule | Queue |
|------|----------|-------|
| `refresh_top100` | Hourly 9am–5pm ET weekdays | ml_inference |
| `run_daily_pipeline` | 10pm ET weekdays | ml_inference |
| `scrape_social_media` | Every 30 min | default |
| `fetch_fundamentals` | 8am ET weekdays | default |
| `validate_symbol_requests` | Every 6h | default |

The following are **not** in the Celery beat schedule — they run via backend lifespan threads (startup + periodic). Celery tasks remain defined for manual invocation:
- **Earnings** (`fetch_earnings`): startup + 2×/weekday (08:00 ET pre-market, 18:00 ET post-market). See `docs/earnings.md`.
- **Celebrity holdings** (`fetch_congress_trades`, `fetch_13f_filings`, `fetch_ark_trades`): startup + daily 19:00 ET.
- **News** (`data.news.scheduler`): startup full ingest + tier-1 (MAG7 + top ETFs) every 15 min + tier-2 (rest) every 60 min. Source priority: Massive (paid) → Google News RSS (free) → Finnhub (free tier, last resort). FinBERT scores each headline per ticker.

## Data Sources

| Source | What | How | Status |
|--------|------|-----|--------|
| User's own data | 30-min + daily bars 2000–present (6,300 symbols) | `db/market_data/import_features_to_timescale.py` (`make import-30min`) → `bars_30m`/`bars_1d` | ✅ loaded (~236M rows) |
| IBKR WebSocket | Real-time 1-min bars during market hours (50 core symbols) | `data/ingestion/realtime/ibkr_service.py` | ✅ live |
| Finnhub WebSocket | Real-time trade ticks → 1-min bars (same 50 symbols, hot standby) | `data/ingestion/realtime/finnhub_ws.py` | ✅ live |
| Massive (massive.com) | Minute history + reference + market cap + symbol validation (~15 min delay) | `data/ingestion/massive_*.py`, `ml/tasks/symbol_validation.py` | ✅ live |
| Finnhub REST | Earnings calendar (EPS actual/estimate/surprise) | `data/earnings/finnhub.py` + `data/earnings/scheduler.py` (startup + 2×/day) | ✅ live |
| SEC EDGAR 13F/13D | Institutional holdings (Buffett, Soros, Dalio, Ackman) + Trump DJT | `data/celebrity/sec_13f.py` | ✅ live (daily auto-fetch) |
| Quiver Quant | Congressional trades (Pelosi, Tuberville, MTG, Crenshaw) | `data/celebrity/congress.py` | ✅ live (daily auto-fetch) |
| arkfunds.io | ARK Invest daily trades (Cathie Wood) | `data/celebrity/ark.py` | ✅ live (daily auto-fetch) |
| Massive — news | Hot-ticker news headlines + sentiment | `data/news/ingest.py` → `news_articles` hypertable | ✅ live (startup + tiered periodic) |
| Google News RSS | Free news fallback (no API key, no sentiment) | `data/news/ingest.py`, `backend/app/api/routes/news.py` | ✅ live (fallback) |
| Finnhub — news | Company news (free tier, 60 req/min) | `data/news/ingest.py` (last resort only) | ✅ live (last resort) |
| Federal Reserve | FOMC statements + hawk/dove scores (FinBERT) | `data/fomc/` (scraper + scorer + loader) → `fomc_statements` | ✅ live (`make fetch-fomc`) |
| CNN — Fear & Greed | Stock-market Fear & Greed Index (7-factor) + VIX/VVIX volatility | `data/fear_greed/` (CNN + CBOE/Yahoo/FRED) → `fear_greed_index`/`volatility_index`; `fng-sched` thread (startup + session-aware: 8 min regular session, 15 min pre/after, 60 min off-session, forced pull at open/close boundaries; staleness guard; publishes health to `app.state.fng_health` → admin data-source panel, flags CNN-down/VIX-proxy fallback); multi-year real-CNN history backfilled via `scripts/backfill_fear_greed.py` (CNN graphdata serves history back to ~2020-09 when a start date is in the path) | ✅ live |
| Twitter/X · Reddit | Social sentiment | `data/scrapers/*` (Playwright / PRAW) | 🚧 planned — not created |
| Polygon.io | Historical minute bars (supplemental) | — | ❌ legacy (no loader; superseded by Massive) |

## Realtime Dual-Source Architecture

IBKR and Finnhub run in parallel for the 50 core symbols. Both write to `market_data_1min`
concurrently; the upsert's `ON CONFLICT` keeps data consistent. Neither is "primary" or
"fallback" — whichever source writes first for a given (ticker, time) wins; the other's
upsert becomes a no-op (IBKR rows are preserved over Finnhub if both arrive).

```
IBKR stream (亚秒延迟)  ──┐
                          ├──→ market_data_1min (ON CONFLICT upsert)
Finnhub WS (~150ms 延迟) ──┘
                          │
                    CrossValidator
                    (每 30s 比较两边价格)
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
    IBKR stale? → log warning   Finnhub stale? → log warning
    Price divergence >2%? → log error (possible zombie)
```

**Key files:**
- `data/ingestion/realtime/finnhub_ws.py` — Finnhub WS client + tick→bar aggregation + CrossValidator
- `data/ingestion/realtime/ibkr_service.py` — IBKR stream + 3-layer zombie detection + feeds CrossValidator
- `data/ingestion/realtime/supervisor.py` — starts both + shared CrossValidator instance

**Config:** `FINNHUB_API_KEY` (in `.env`), `FINNHUB_WS_ENABLED=true` (default).
Finnhub free tier: 50 symbols, real-time US SIP trades, ~150ms latency.

## Frontend Rules

- **Dark theme only.** Background: zinc-950 (`#09090b`). Never use white backgrounds.
- LONG signals: emerald green. SHORT signals: red. NEUTRAL: zinc gray.
- Signal confidence shown as a progress bar, not just a number.
- TradingView Lightweight Charts for all candlestick charts (package: `lightweight-charts`).
- API calls via `frontend/src/lib/api.ts` only — never fetch directly from components.
- Types live in `frontend/src/lib/types.ts`. Keep in sync with backend Pydantic schemas.

## Commands

The `Makefile` is the canonical command runner — prefer it over raw commands.

```bash
# ── Run ───────────────────────────────────────────────
make up            # full stack via docker-compose (detached)
make down / logs   # stop / tail logs
make backend       # uvicorn app.main:app --reload --port 8000  (run from backend/)
make frontend      # next dev --turbo  (run from frontend/)
make ml-worker     # Celery worker, ml_inference queue — MUST run from repo root
make celery-beat   # scheduler  |  make flower  → task monitor on :5555

# ── Quality (run before pushing; mirrors .github/workflows/ci.yml) ──
make lint          # ruff check (backend/ml/data/scripts) + next lint
make lint-fix      # ruff check --fix + ruff format
make type-check    # mypy backend/app + ml  |  npx tsc --noEmit (frontend)
make test          # pytest backend/tests + ml/tests

# ── DB / data ─────────────────────────────────────────
make db-init       # apply db/schema/*.sql into the timescaledb container
make bootstrap     # scripts/bootstrap_universe.py — populate ticker universe (run once)

# ── Celebrity holdings ────────────────────────────
make fetch-reference    # company/ETF names (Massive) → upsert tickers.name/exchange (stock-page header)
make fetch-fomc         # FOMC statements → fomc_statements (Fed website + FinBERT scoring)
make fetch-celebrities  # all three sources at once
make fetch-congress     # congressional trades (Quiver Quant)
make fetch-13f          # SEC EDGAR 13F/13D (Buffett, Soros, Dalio, Ackman, Trump)
make fetch-ark          # ARK Invest daily trades (Cathie Wood)
```

Run a single Python test: `pytest backend/app/api/routes/tests/test_signals.py::test_name -v`
(pytest config in `pyproject.toml`; `asyncio_mode=auto`, so async tests need no decorator).
Frontend has no test runner configured — CI gates it via `tsc --noEmit` + `next lint` + `next build`.

**Tooling:** ruff (line-length 100, double quotes), mypy (non-strict, ignores missing imports),
Python 3.12, Node 22. `make ml-worker` resolves the `ml.tasks.celery_app` import path only from
the repo root — never `cd ml` first.

> Tests are colocated next to the code they cover — `backend/app/**/tests/test_*.py`
> (e.g. `app/api/routes/tests/`, `app/core/tests/`). `pyproject.toml:testpaths` scans
> `backend/app`, `backend/tests`, and `ml/tests`, so any `test_*.py` under those wires into
> `make test` / CI automatically. `ml/tests/` does not exist yet.

## What NOT to do

- Keep the **signal pipeline** native Python async — do not wrap that deterministic, backend-assembled path in an agent/orchestration framework. The **LLM Chat Agent** MAY adopt an agent framework (e.g. Google ADK, Pydantic AI, OpenAI Agents SDK) when it earns its keep, provided it keeps the dependency footprint reasonable and preserves the non-negotiable chat security model (read-only tools, server-side `user_id`, injection mitigations, no write/execution tools — see "LLM Chat Agent"). Avoid LangChain specifically (bloat).
- Do not let user free text reach the **signal pipeline** LLM — those prompts are 100% backend-assembled. (The separate **LLM Chat Agent** does accept user input; it gets its own injection mitigations, read-only tools, and server-side `user_id` scoping. Never give the chat agent write/execution tools.)
- Do not write trading/order execution code. Signals only — this applies to chat-agent tools too (read-only).
- Do not use Streamlit for the user-facing product. Streamlit is for internal ML monitoring only.
- Do not run ML training inside the FastAPI process. Always dispatch to Celery ml_inference queue.
- Do not store raw API keys in code. All secrets via `.env` / environment variables.
