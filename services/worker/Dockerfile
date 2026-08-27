# ============================================
# STAYKARO AI CALLER — Worker Service
# Python 3.12 slim — multi-stage build
# ============================================

# -------------------------------------------
# STAGE 1: Builder — install dependencies
# -------------------------------------------
FROM python:3.12-slim AS builder

# Prevent Python from writing .pyc files & buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Phase 6: redis (queue) + httpx (internal job/integration API clients) +
# pydantic (response models) — all pure-Python/prebuilt-wheel, no system
# build toolchain (gcc/libpq-dev) needed. The worker never opens its own
# PostgreSQL connection (see src/main.py's module docstring — job state
# lives in services/api's PostgreSQL, reached only through its internal
# HTTP API), so no Postgres client library belongs here either.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# -------------------------------------------
# STAGE 2: Runtime — minimal production image
# -------------------------------------------
FROM python:3.12-slim AS runtime

# Prevent Python from writing .pyc files & buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy virtual environment from builder (preserves layer caching)
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Application code
COPY src/ ./src/

# Ensure the app directory is owned by the non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Worker service does not expose an HTTP port — runs background jobs only.
# No Docker HEALTHCHECK: there is no HTTP surface to probe. Operational
# health is instead observed through structured stdout logging (startup
# checks, per-job outcomes) and services/api's job table itself (a worker
# that stopped processing shows up as jobs no longer leaving 'queued').

CMD ["python", "-m", "src.main"]
