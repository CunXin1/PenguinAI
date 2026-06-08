# PenguinAI — TODO / Backlog

> Status snapshot: **2026-06-08**. Running backlog of unfinished work, stubs, and known gaps.
>
> 优先级:🔴 阻塞性 · 🟡 重要 · 🟢 锦上添花

**Legend:** 🔴 blocker · 🟡 important · 🟢 nice-to-have

---

## 0. Critical path — what blocks a real end-to-end run

- 🔴 **No trained model artifacts** — `/models/penguinai/xgboost_prod.pkl` and `rf_prod.pkl` don't exist, so `ml/models/model_registry.py` returns `None` and all ML probabilities are `None`. **Need a first training run.**
- 🔴 **Training not wired to data** — `ml/tasks/daily_pipeline.py` passes `db_path=":memory:"`; the trainer expects a DuckDB/Parquet feature store. Point it at the `data/30min_data` parquet (the train/serve-parity source).
- 🟡 **Trainer ↔ indicators feature parity** — `ml/models/xgboost_trainer.py:FEATURE_COLS` are *normalized/derived* features (`bb_pct_b`, `atr_14_pct`, `ema20_slope`, `price_vs_sma200`, `volume_ratio`, `vwap_pct`). The `indicators_30min` view (`04_compat_views.sql`) is meant to expose exactly these derived columns over the raw-level `bars_30m` fields. **Verify** the view's output columns match `FEATURE_COLS` 1:1 before the first training run.

---

## 1. Data layer

- 🟡 Social scrapers **not built** — `data/scrapers/` does not exist yet (no Twitter/Reddit/SEC modules). `social_posts`, `celebrity_holdings` stay empty; the `scrape_social_media` Celery task is a stub. 13F parsing + FinBERT scoring still to write.
- 🟡 FOMC ingestion + hawk/dove scoring — no population path for `fomc_statements` (the macro filter reads it; no-ops while empty).
- 🟢 News ingestion — `news_articles` table exists but nothing scrapes/populates it (and there's no `/api/news` endpoint).
- 🟢 Polygon — `POLYGON_API_KEY` lingers in `.env`/schema `source` enum but there's no `polygon_loader.py`; superseded by Massive. Remove or implement.

## 2. ML layer

- 🔴 First training run → produce prod pickles; verify hot-reload via `model_registry.reload()`.
- 🔴 Wire trainer to a real DuckDB/Parquet path (replace `:memory:`).
- 🟡 `fetch_fundamentals` stub — `ml/tasks/daily_pipeline.py:89` only logs. `fundamentals` + `earnings` tables stay empty → `get_fundamentals()` always returns `None`.
- 🟡 FinBERT (`ProsusAI/finbert`) — confirm model download/caching in the ML worker image.
- 🟡 Gemma 4 inference server — needs a running vLLM endpoint (`GEMMA_API_URL`). `gemma_agent` retries 3× then raises if absent.
- 🟡 RAG embedder (sentence-transformers MiniLM → `VECTOR(384)`) — confirm model + tune the pgvector `ivfflat` index.
- 🟢 Backtest / signal-quality evaluation harness (precision by horizon, calibration).

## 3. Backend

- 🟡 **Alembic baseline missing** — `backend/alembic.ini` exists and `db/migrations/` has `env.py` + template, but there are **no version files**. Schema is still created from `db/schema/*.sql` via `docker-entrypoint-initdb.d`. Generate a baseline migration aligned to the ORM models + `db/schema`, then wire `alembic upgrade head` into deploy.
- 🟡 **No `/api/news` endpoint** — `news_articles` is unused by the API; the frontend News pages are mock-only.
- 🟡 `GET /api/signals/{ticker}` requires auth (`CurrentUser`) — anonymous users get **401** on the detail page even though `/signals/top` is public. Decide gating (use `OptionalUser`, or gate by tier only).
- 🟡 **Forgot-password email delivery not wired** — `POST /forgot-password` generates a reset token but only logs it. Need an email transport (SES, Resend, etc.) to actually deliver the reset link.
- 🟢 OAuth — `auth.py` returns **501** (Google / Apple, future).
- 🟢 PREMIUM features — API-key access + LLM chat (future per `CLAUDE.md`).

## 4. Frontend

> UI is built across all pages, but some still run on **demo data** (`src/lib/mock.ts`) with silent API fallback. The work below is mostly *wiring to live endpoints*.

- 🟡 Dashboard Top Signals — `useTopSignals` already tries the API then falls back; verify against a live backend.
- 🟡 Screener → `GET /api/tickers/universe` (currently `MOCK_UNIVERSE`).
- 🟡 Watchlist → `GET/POST/DELETE /api/watchlist` (currently `localStorage`; needs auth/session).
- 🟡 News → needs a backend `/api/news` (no endpoint yet).
- 🟡 Auth/session — `zustand` is installed but **unused**; there's only a `localStorage` token check. Add an auth store, protected routes, token-expiry handling.
- 🟡 Nav search → wire to `/api/tickers/search` autocomplete (today it blind-pushes to `/signals/<input>`).
- 🟢 `loading.tsx` / `error.tsx` boundaries, custom `not-found`, skeleton polish.
- 🟢 Login page renders under the global Navbar — consider an auth route group without the nav.
- 🟢 Mobile/responsive QA + accessibility pass.
- 🟢 Forgot-password + reset-password pages — backend endpoints exist, frontend `api.ts` methods exist, but no dedicated pages built yet.

## 5. Infra / DevOps

- 🟡 **Docker Hub is blocked** on the dev network → pull base images via the **DaoCloud mirror**. Consider setting `registry-mirrors` in `daemon.json`.
- 🟡 **Frontend hot-reload is dead** over the Windows bind mount → `docker restart penguinai-frontend` to apply edits.
- 🟡 `.env` exists (copied from `.env.example`). Still blank/optional: `GEMMA_*`, `REDDIT_*` (scrapers unbuilt), `POLYGON_API_KEY` (legacy). Note: `FINNHUB_API_KEY` is referenced by `make fetch-earnings` but **not yet listed in `.env.example`** — add it.
- 🟡 Full-stack `docker-compose up` is **unverified end-to-end** (needs DB data + model pickles + a Gemma endpoint).
- 🟢 GPU (`ml_worker`) NVIDIA runtime config on the 4090 box.
- 🟢 AWS deploy (`.github/workflows/cd-aws.yml`) — ECR/ECS + secrets not provisioned.

## 6. Testing & quality

- 🟡 **Coverage thresholds not enforced** — neither `pytest --cov-fail-under` nor vitest coverage gates are configured. Target: 85% backend, reasonable frontend coverage. Wire into CI as blocking check.
- 🟡 **Auth test gaps** — existing `test_auth` covers register/login/me/token/OAuth but does **not** test `forgot-password`, `reset-password`, `change-password`, or password strength validation rejection. Add ~6–8 tests.
- 🟡 ML — unit tests for `technical.compute_features` (no look-ahead), Gemma output validation, `signal_engine` orchestration with mocks. `ml/tests/` does not exist yet.
- 🟢 Pre-commit hooks (ruff / black / eslint / prettier).

## 7. Code-level TODOs (grep hits)

| File | Line | Note |
|------|------|------|
| `ml/tasks/daily_pipeline.py` | ~32 | `db_path=":memory:"` → wire to the `data/30min_data` Parquet feature source |
| `ml/tasks/daily_pipeline.py` | ~84 | `fetch_fundamentals` is a logging stub |
| `ml/tasks/realtime_ingest.py` | ~14 | `scrape_social_media` is a stub — social scrapers (`data/scrapers/`) not created yet |
| `backend/app/api/routes/auth.py` | ~109 | `# TODO: send email with reset link containing token` — email transport not wired |
| `backend/app/api/routes/auth.py` | ~165 | OAuth returns 501 (future) |

## 8. Schema-contract reminders (from CLAUDE.md)

- The **signal output schema** must stay synchronized across three places: the `signal_cache` table ↔ `backend/app/schemas/signal.py` ↔ `frontend/src/lib/types.ts`. Change them together.
- `FEATURE_COLS` in `ml/models/xgboost_trainer.py` is the **single source of truth** for ML features.
- No user free-text may ever reach the LLM — all Gemma prompts are backend-assembled.
