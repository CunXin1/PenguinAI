FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install backend deps (layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Install lightweight data deps needed by lifespan threads (celebrity, earnings, news, realtime)
# transformers + torch pulled from ml/requirements.txt only for FinBERT scorer used in news route
COPY ml/requirements.txt /app/ml/requirements.txt
RUN pip install --no-cache-dir -r ml/requirements.txt || true

# Copy full repo packages that backend imports at runtime
COPY backend/ /app/backend/
COPY data/ /app/data/
COPY ml/ /app/ml/
COPY scripts/ /app/scripts/

WORKDIR /app/backend

# Docker runs Celery as separate containers — disable the embedded watchdog
ENV CELERY_EMBEDDED=false
ENV REALTIME_ENABLED=false

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
