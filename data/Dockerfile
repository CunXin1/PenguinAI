FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY data/ingestion/requirements.txt /app/data-requirements.txt
RUN pip install --no-cache-dir -r data-requirements.txt

# Playwright for Twitter scraper
RUN pip install --no-cache-dir playwright praw httpx pydantic-settings python-dotenv \
    sqlalchemy[asyncio] asyncpg \
    && playwright install chromium --with-deps

COPY data/ /app/data/
COPY scripts/ /app/scripts/

# CMD set per-service in docker-compose.yml
