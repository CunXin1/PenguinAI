# PenguinAI — TODO / Backlog

> Status snapshot: **2026-06-05**. This is the running backlog of unfinished work, stubs, and known gaps across all layers.
>
> 本文件汇总当前所有未完成项、桩代码与缺口。优先级:🔴 阻塞性 · 🟡 重要 · 🟢 锦上添花 · ✅ 已完成。

**Legend:** 🔴 blocker · 🟡 important · 🟢 nice-to-have · ✅ done

---

## 0. Critical path — what blocks a real end-to-end run

- 🔴 **Historical data import** — a bulk loader now **exists** (`db/market_data/import_features_to_timescale.py`: per-symbol Parquet → `bars_30m`/`bars_1d` via `COPY` + index drop/rebuild). Remaining: **reconcile table names** (`bars_30m` vs the project's `market_data_30min`/`market_data_daily`/`indicators_30min`) and **actually run it** on the cleaned `data/30min_data` + `data/daily_data`. See §1.
- 🟡 **Data-quality in the Parquet** — largely addressed (2026-06-05, see §1): ticker-reuse seams truncated, coverage holes backfilled, and `compute_indicators._segment_id` resets recursive indicators (EMA/MACD/RSI/ATR/OBV/ret_1bar) at adj-discontinuities so a bad boundary bar can't pollute across eras. **Still decide storage before the 170M-row import:** `raw` + adjustment factor (recommended, precision-safe) vs. storing `adj` directly (`NUMERIC(14,4)` loses precision on deeply-adjusted small prices). Re-validate the warm-up `ret_1bar` after import.
- 🔴 **No trained model artifacts** — `/models/penguinai/xgboost_prod.pkl` and `rf_prod.pkl` don't exist, so `ml/models/model_registry.py` returns `None` and all ML probabilities are `None`. **Need a first training run.**
- 🔴 **Training not wired to data** — `ml/tasks/daily_pipeline.py:32` passes `db_path=":memory:"`; the trainer expects a DuckDB/Parquet feature store that doesn't exist yet.
- 🔴 **Trainer ↔ indicators feature mismatch** — `ml/models/xgboost_trainer.py:FEATURE_COLS` are *normalized/derived* features (`bb_pct_b`, `atr_14_pct`, `ema20_slope`, `price_vs_sma200`, `volume_ratio`, `vwap_pct`) that do **not** match the raw-level columns in the `indicators_30min` table **or** the Parquet field names (`bb_pctb`, `bb_bw`, `atr_14`, …). The training `JOIN` will fail or return the wrong columns. Reconcile `ml/features/technical.py`, the `indicators_30min` schema, and the Parquet.

---

## 1. Data layer

- ✅ **Per-symbol Parquet cleanup (2026-06-05)** — the 6,300-symbol 30-min/daily set was audited and repaired:
  - **Ticker-reuse seams** (one file = two unrelated companies, e.g. `SII` = Smith Intl→Sprott, `FG` = old Fidelity&Guaranty→F&G): **26 symbols truncated** to the new entity (old pre-gap segment dropped). Reversible backups in `30min_data/_reuse_backup/`.
  - **Coverage holes** (continuous issuer missing mid-history, e.g. `CAG` missing 2017-01→2025-09): backfilled from **IBKR 30-min** (raw paged backward; adj rebuilt whole-series from IBKR daily factor = "Option B"; vol calibrated). 4 safety gates auto-skip reuse/SPAC/degraded tickers. CAG+BWXT+PEG+NVDW+ETH done; batch running for the rest (~20 legit holes). Backups in `30min_data/_backfill_backup/`.
  - Indicators recomputed per repaired symbol (`backend/scripts/market_data/compute_indicators.py`, which already resets indicators at adj-discontinuities via `_segment_id`).
  - Tooling (host has no Python): duckdb CLI for parquet + `uv`-managed venv with `ib_async`.
  - **Still pending:** the 7 "uncertain" reuse/relist symbols (PAYS/ACIC/TROO/CORZ/AEHL/GSOL/NBIS) await a truncate-vs-backfill decision; and the bulk import below.
- 🔴 Parquet → TimescaleDB importer — **code exists** at `db/market_data/import_features_to_timescale.py` (loads `by_symbol`/`features_daily` Parquet → `bars_30m`/`bars_1d`), but (a) it has **not been run** on the cleaned data, and (b) its table names (`bars_30m`/`bars_1d`) **don't match** the project's expected `market_data_30min`/`market_data_daily`/`indicators_30min` — reconcile names (rename in importer, or point the backend at `bars_30m`) before importing. Uses `COPY` + drop/rebuild indexes (good).
- 🟡 `data/scrapers/sec_scraper.py:39` — 13F holdings parsing is a `TODO` (returns `[]`). `celebrity_holdings` stays empty until done.
- 🟡 FOMC ingestion + hawk/dove scoring — no clear population path for `fomc_statements` (the macro filter reads it).
- 🟡 `data/requirements.txt` is **missing** (the `data/Dockerfile` inlines deps). Add for parity / non-Docker runs.
- 🟢 News ingestion — `news_articles` table exists but nothing scrapes/populates it.

## 2. ML layer

- 🔴 First training run → produce prod pickles; verify hot-reload via `model_registry.reload()`.
- 🔴 Wire trainer to a real DuckDB/Parquet path (replace `:memory:`).
- 🟡 `fetch_fundamentals` stub — `ml/tasks/daily_pipeline.py:89` only logs. `fundamentals` + `earnings` tables stay empty → `get_fundamentals()` always returns `None`.
- 🟡 FinBERT (`ProsusAI/finbert`) — confirm model download/caching in the ML worker image.
- 🟡 Gemma 4 inference server — needs a running vLLM endpoint (`GEMMA_API_URL`). `gemma_agent` retries 3× then raises if absent.
- 🟡 RAG embedder (sentence-transformers MiniLM → `VECTOR(384)`) — confirm model + tune the pgvector `ivfflat` index.
- 🟢 Backtest / signal-quality evaluation harness (precision by horizon, calibration).

## 3. Backend

- 🟡 **Alembic baseline missing** — `backend/alembic.ini` now **exists** and `db/migrations/` has `env.py` + template, but there are **no version files** (no baseline migration). Schema is still created from `db/schema/*.sql` via `docker-entrypoint-initdb.d`. Generate a baseline migration aligned to the ORM models + `db/schema`, then wire `alembic upgrade head` into deploy.
- 🟡 **No `/api/news` endpoint** — `news_articles` is unused by the API; the frontend News pages are mock-only.
- 🟡 `GET /api/signals/{ticker}` requires auth (`CurrentUser`) — anonymous users get **401** on the detail page even though `/signals/top` is public. Decide gating (use `OptionalUser`, or gate by tier only).
- 🟢 OAuth — `auth.py:59` returns **501** (Google / Apple, future).
- 🟢 PREMIUM features — API-key access + LLM chat (future per `CLAUDE.md`).
- 🟢 Rate limiting, structured request logging, standardized error envelope.

## 4. Frontend

> UI is built across all pages (✅), but everything runs on **demo data** (`src/lib/mock.ts`) with a silent API fallback. The work below is mostly *wiring to live endpoints*.

- ✅ Pages built: Dashboard, Screener, Watchlist, News + article detail, Profile, Signal detail (+ candlestick chart), Login.
- 🟡 Dashboard Top Signals — `useTopSignals` already tries the API then falls back; verify against a live backend.
- 🟡 Screener → `GET /api/tickers/universe` (currently `MOCK_UNIVERSE`).
- 🟡 Watchlist → `GET/POST/DELETE /api/watchlist` (currently `localStorage`; needs auth/session).
- 🟡 Signal detail chart → real `GET /api/market-data/{ticker}/candles` (currently `mockCandles`).
- 🟡 News → needs a backend `/api/news` (no endpoint yet).
- 🟡 Auth/session — `zustand` is installed but **unused**; there's only a `localStorage` token check. Add an auth store, protected routes, token-expiry handling.
- 🟡 Nav search → wire to `/api/tickers/search` autocomplete (today it blind-pushes to `/signals/<input>`).
- 🟢 `loading.tsx` / `error.tsx` boundaries, custom `not-found`, skeleton polish.
- 🟢 Login page renders under the global Navbar — consider an auth route group without the nav.
- 🟢 Mobile/responsive QA + accessibility pass.

## 5. Infra / DevOps

- 🟡 **Docker Hub is blocked** on the dev network → pull base images via the **DaoCloud mirror** (`docker.m.daocloud.io/library/<img>` then retag). See `frontend/README.md`. Consider setting `registry-mirrors` in `daemon.json` so the whole compose stack builds.
- 🟡 **Frontend hot-reload is dead** over the Windows bind mount → `docker restart penguinai-frontend` to apply edits (or recreate with `WATCHPACK_POLLING=true` + webpack).
- 🟡 `.env` not present (only `.env.example`). Required secrets: `SECRET_KEY`, `DB_PASSWORD`, `POLYGON_API_KEY`, `REDDIT_*`, `GEMMA_*`.
- 🟡 Full-stack `docker-compose up` is **unverified end-to-end** (needs DB data + model pickles + a Gemma endpoint).
- 🟢 GPU (`ml_worker`) NVIDIA runtime config on the 4090 box.
- 🟢 AWS deploy (`.github/workflows/cd-aws.yml`) — ECR/ECS + secrets not provisioned.

## 6. Testing & quality

- 🔴 **No test suite anywhere** (backend / ml / frontend). `ci.yml` runs but has nothing meaningful to assert.
- 🟡 Backend — `pytest` + `httpx` for routes, auth, tier gating, the 200/202 cache flow.
- 🟡 ML — unit tests for `technical.compute_features` (no look-ahead), Gemma output validation, `signal_engine` orchestration with mocks.
- 🟡 Frontend — `tsc --noEmit` in CI, plus component tests for `SignalCard` / screener sort/filter.
- 🟢 Pre-commit hooks (ruff / black / eslint / prettier).

## 7. Code-level TODOs (grep hits)

| File | Line | Note |
|------|------|------|
| `ml/tasks/daily_pipeline.py` | 32 | `db_path=":memory:"` → wire to DuckDB Parquet export |
| `ml/tasks/daily_pipeline.py` | 89–90 | `fetch_fundamentals` is a logging stub |
| `data/scrapers/sec_scraper.py` | 39 | parse 13F holdings from the infotable |
| `backend/app/api/routes/auth.py` | 59 | OAuth returns 501 (future) |

## 8. Schema-contract reminders (from CLAUDE.md)

- The **signal output schema** must stay synchronized across three places: the `signal_cache` table ↔ `backend/app/schemas/signal.py` ↔ `frontend/src/lib/types.ts`. Change them together.
- `FEATURE_COLS` in `ml/models/xgboost_trainer.py` is the **single source of truth** for ML features.
- No user free-text may ever reach the LLM — all Gemma prompts are backend-assembled.
