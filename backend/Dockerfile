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

# Run as a non-root user (defense in depth). --create-home gives the FinBERT
# scorer a writable ~/.cache/huggingface for model downloads at runtime.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend

# Docker runs Celery as separate containers — disable the embedded watchdog
ENV CELERY_EMBEDDED=false
ENV REALTIME_ENABLED=false
# Uvicorn worker count, overridable at deploy time (async app: ~1–2× CPU cores).
ENV WEB_CONCURRENCY=4

EXPOSE 8000

# Liveness probe from inside the container (no external deps); /health/live
# returns 200 as soon as the app is serving.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/live || exit 1

# Shell form so ${WEB_CONCURRENCY} expands; `exec` makes uvicorn PID 1 so it
# receives SIGTERM directly and shuts down gracefully (runs the lifespan finally).
CMD exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4}
