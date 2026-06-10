FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY data/ingestion/requirements.txt /app/data-requirements.txt
RUN pip install --no-cache-dir -r data-requirements.txt

# Playwright for Twitter scraper. Pin browsers to a shared path so the non-root
# runtime user can read them (the default install location is under $HOME).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir playwright praw httpx pydantic-settings python-dotenv \
    sqlalchemy[asyncio] asyncpg \
    && playwright install chromium --with-deps

COPY data/ /app/data/
COPY scripts/ /app/scripts/

# Run as a non-root user (defense in depth).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser

# CMD set per-service in docker-compose.yml
