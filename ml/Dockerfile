FROM python:3.12-slim

# CUDA runtime is provided by the host via nvidia-container-toolkit
# Install system deps for ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch / torchvision: CPU wheels by default so the image builds on Mac/ARM and
# CPU-only Linux. On a CUDA host, build with:
#   --build-arg TORCH_SPEC="torch==2.5.1+cu124 torchvision==0.20.1+cu124" \
#   --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
ARG TORCH_SPEC="torch==2.5.1 torchvision==0.20.1"
ARG TORCH_INDEX_URL=""
RUN if [ -n "$TORCH_INDEX_URL" ]; then \
        pip install --no-cache-dir --extra-index-url "$TORCH_INDEX_URL" ${TORCH_SPEC}; \
    else \
        pip install --no-cache-dir ${TORCH_SPEC}; \
    fi

# Install Python deps first (layer caching)
COPY ml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright browsers for Twitter scraper. Pin to a shared path so a
# non-root runtime user can read them (the default location is under $HOME).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# --with-deps apt-installs OS libs but on Debian-arm64 it tries Ubuntu-only font
# packages that don't exist and fails. Fall back to a browser-only install (a
# plain download, no apt) so the image still builds; the system font libs are
# cosmetic and the Twitter scraper that needs chromium isn't live yet.
RUN pip install --no-cache-dir playwright \
    && (playwright install chromium --with-deps || playwright install chromium)

COPY ml ./ml
COPY data ./data

# Run as a non-root user (defense in depth). chown the code + browser bundle so
# the celery workers can read them and write celerybeat-schedule under /app.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser

# CMD is set per-service in docker-compose.yml
# e.g. celery -A ml.tasks.celery_app worker --queues=ml_inference -c 1
