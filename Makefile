.PHONY: up down logs backend frontend ml-worker ibkr-stream minute-parquet fetch-earnings fetch-congress fetch-13f fetch-ark fetch-celebrities lint type-check test test-backend test-frontend db-init bootstrap

# ── Docker Compose ────────────────────────────────────────────────────────────
up:
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
	cd frontend && npm run dev

ml-worker:
	cd . && celery -A ml.tasks.celery_app worker --queues=ml_inference -c 1 --loglevel=info

# Live IBKR 1-min bars → market_data_1min (needs TWS/Gateway + DB). Run from repo root.
ibkr-stream:
	python -m data.ingestion.ibkr_stream

# Massive (massive.com) 1-min history → data/minute_data/ parquet (Nasdaq-100 +
# Top-20 ETF, ~2yr). Run from repo root with a venv that has httpx+pyarrow
# (e.g. backend/.venv) and MASSIVE_API_KEY in .env. Resumable (skips existing).
minute-parquet:
	python -m data.ingestion.massive_minute_parquet

# Finnhub (free tier) earnings calendar → earnings table. Run from repo root with
# a venv that has httpx+sqlalchemy+asyncpg and FINNHUB_API_KEY set in .env.
# Idempotent: re-run to backfill actuals once results publish.
fetch-earnings:
	python -m data.earnings.finnhub

# Celebrity holdings ingestion (all free, no API keys needed).
fetch-congress:
	python -m data.celebrity.congress

fetch-13f:
	python -m data.celebrity.sec_13f

fetch-ark:
	python -m data.celebrity.ark

fetch-celebrities: fetch-congress fetch-13f fetch-ark

celery-beat:
	cd . && celery -A ml.tasks.celery_app beat --loglevel=info

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
