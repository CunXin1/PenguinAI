FROM python:3.12-slim

# CUDA runtime is provided by the host via nvidia-container-toolkit
# Install system deps for ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY ml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright browsers for Twitter scraper
RUN pip install --no-cache-dir playwright && playwright install chromium --with-deps

COPY ml ./ml
COPY data ./data

# CMD is set per-service in docker-compose.yml
# e.g. celery -A ml.tasks.celery_app worker --queues=ml_inference -c 1
