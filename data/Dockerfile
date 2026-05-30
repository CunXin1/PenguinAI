FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Scraper deps (subset of ml/requirements.txt — no torch/transformers)
RUN pip install --no-cache-dir \
    praw==7.8.1 \
    playwright==1.49.0 \
    httpx==0.28.1 \
    celery[redis]==5.4.0 \
    redis==5.2.1 \
    sqlalchemy[asyncio]==2.0.36 \
    asyncpg==0.30.0 \
    pydantic-settings==2.7.0 \
    python-dotenv==1.0.1

RUN playwright install chromium --with-deps

COPY . .

CMD ["python", "-m", "data.scrapers.runner"]
