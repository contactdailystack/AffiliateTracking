# Multi-stage build for Worker
FROM python:3.12-slim AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY mvp/worker/requirements.txt .

# Create wheels for faster final image build
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# Runtime stage
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy wheels from builder
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

# Install from wheels
RUN pip install --no-cache-dir /wheels/*

# Copy application code
COPY --chown=appuser:appuser mvp /app/mvp

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD celery -A mvp.worker.celery_app inspect active_queues || exit 1

CMD ["sh", "-c", "celery -A mvp.worker.celery_app worker --loglevel=${CELERY_LOG_LEVEL:-INFO} --concurrency=${CELERY_CONCURRENCY:-4} --prefetch-multiplier=${CELERY_PREFETCH_MULTIPLIER:-1} --max-tasks-per-child=${CELERY_MAX_TASKS_PER_CHILD:-100}"]
