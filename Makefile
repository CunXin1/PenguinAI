.PHONY: up down logs backend frontend ml-worker lint type-check test db-init bootstrap

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
	pytest backend/tests/ ml/tests/ -v

test-backend:
	pytest backend/tests/ -v

# ── Database ──────────────────────────────────────────────────────────────────
db-init:
	@echo "Applying schema files..."
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/01_extensions.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/02_timeseries.sql
	docker-compose exec timescaledb psql -U penguinai -d penguinai -f /docker-entrypoint-initdb.d/03_relational.sql

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
