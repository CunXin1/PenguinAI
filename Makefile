.PHONY: up down logs backend frontend ml-worker gemma-serve gemma-check ibkr-stream minute-parquet fetch-earnings fetch-fomc fetch-fear-greed backfill-fear-greed fetch-congress fetch-13f fetch-ark fetch-celebrities lint type-check test test-backend test-frontend db-init bootstrap verify-existing-users status dev

# ── Docker Compose ────────────────────────────────────────────────────────────
up:
	@bash scripts/ensure_ollama.sh
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

build:
	docker-compose build

# ── Local development (no Docker) ─────────────────────────────────────────────
backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && NODE_OPTIONS="--max-old-space-size=1024" npm run dev

# Start backend + frontend together; frontend auto-restarts on crash
dev:
	bash scripts/dev.sh

ml-worker:
	cd . && celery -A ml.tasks.celery_app worker --queues=ml_inference -c 1 --loglevel=info

# ── Gemma 4 local LLM serving (Agent 2 reasoner) ──────────────────────────────
# macOS → Ollama; Windows/Linux GPU → vLLM. See ml/serving/README.md.
gemma-serve:
	@case "$$(uname -s)" in \
	  Darwin) ml/serving/start_ollama.sh ;; \
	  *)      ml/serving/start_vllm.sh ;; \
	esac

# Ping the configured LLM backend + run Agent 2 end-to-end on a synthetic context.
gemma-check:
	PYTHONPATH=. python ml/scripts/llm_healthcheck.py

# Live IBKR 1-min bars → market_data_1min (needs TWS/Gateway + DB). Run from repo root.
ibkr-stream:
	python -m data.ingestion.ibkr_stream

# Massive (massive.com) 1-min history → data/minute_data/ parquet (Nasdaq-100 +
# Top-20 ETF, ~2yr). Run from repo root with a venv that has httpx+pyarrow
# (e.g. backend/.venv) and MASSIVE_API_KEY in .env. Resumable (skips existing).
minute-parquet:
	python -m data.ingestion.massive_minute_parquet

# Finnhub (free tier) earnings calendar → earnings table. Idempotent: re-run to
# backfill actuals once results publish. Requires FINNHUB_API_KEY in .env.
fetch-earnings:
	python -m data.earnings.finnhub

# Celebrity holdings ingestion (all free, no API keys needed).
fetch-congress:
	python -m data.celebrity.congress

fetch-13f:
	python -m data.celebrity.sec_13f

fetch-ark:
	python -m data.celebrity.ark

# Company / ETF names for every instruments symbol → upserted into tickers
# (the authoritative symbol → name dimension; powers the stock-page header).
# Needs MASSIVE_API_KEY in .env. Idempotent.
fetch-reference:
	python -m data.ingestion.massive_reference

# FOMC statements → fomc_statements table. Scrapes Fed website, scores with
# FinBERT. Incremental (skips dates already in DB). No API key needed.
fetch-fomc:
	python -m data.fomc.loader

# Fear & Greed index + VIX/VVIX → fear_greed_index / volatility_index. Live fetch
# (CNN + CBOE/Yahoo/FRED), idempotent upsert. No API key needed (FRED optional).
fetch-fear-greed:
	python -m data.fear_greed.loader

# One-time historical backfill: reconstruct multi-year F&G from the VIX percentile
# model (CNN only serves ~1yr). Safe to re-run — preserves existing CNN rows.
backfill-fear-greed:
	python scripts/backfill_fear_greed.py

fetch-celebrities: fetch-congress fetch-13f fetch-ark

celery-beat:
	cd . && celery -A ml.tasks.celery_app beat --loglevel=info

# ── Monitoring ───────────────────────────────────────────────────────────────
status:
	python3 scripts/status.py

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check backend/ ml/ data/ scripts/
	cd frontend && npm run lint

lint-fix:
	ruff check --fix backend/ ml/ data/ scripts/
	ruff format backend/ ml/ data/ scripts/

type-check:
	mypy backend/app ml/
	cd frontend && npx tsc --noEmit

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	python3 -m pytest backend/app/ ml/tests/ -v
	cd frontend && npx vitest run

test-backend:
	python3 -m pytest backend/app/ -v

test-frontend:
	cd frontend && npx vitest run

# ── Database ──────────────────────────────────────────────────────────────────
db-init:
	@echo "Applying schema files..."
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/01_extensions.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/02_timeseries.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/03_relational.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/04_compat_views.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/05_continuous_aggregates.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/07_celebrity_unique.sql

# Load the 30-min + daily parquet (data/30min_data, data/daily_data) → bars_30m /
# bars_1d in penguinai. Run after `make db-init`. Needs a Python with pyarrow +
# psycopg (the loader connects via PG* env, defaulting to the penguinai container).
import-30min:
	python db/market_data/import_features_to_timescale.py

bootstrap:
	python scripts/bootstrap_universe.py

# One-off: mark all pre-existing accounts as email-verified so the hard
# verification gate doesn't lock out users created before it landed.
verify-existing-users:
	python scripts/verify_existing_users.py

# ── Celery monitoring ─────────────────────────────────────────────────────────
flower:
	celery -A ml.tasks.celery_app flower --port=5555

# ── Dependencies ──────────────────────────────────────────────────────────────
install-backend:
	pip install -r backend/requirements.txt

install-ml:
	pip install -r ml/requirements.txt

install-frontend:
	cd frontend && npm install

install-playwright:
	playwright install chromium
