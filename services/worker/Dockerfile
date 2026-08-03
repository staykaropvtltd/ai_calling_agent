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

# Install system build dependencies required by some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# ---------------------------------------------------------------
# Python dependencies
# Service owner: uncomment the lines below AFTER creating
# a requirements.txt file in this directory with your deps.
# ---------------------------------------------------------------
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt


# -------------------------------------------
# STAGE 2: Runtime — minimal production image
# -------------------------------------------
FROM python:3.12-slim AS runtime

# Prevent Python from writing .pyc files & buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install runtime-only system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (preserves layer caching)
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# ---------------------------------------------------------------
# Application code
# Service owner: uncomment the line below AFTER creating your
# src/ directory with the application entry point.
# ---------------------------------------------------------------
# COPY src/ .

# Ensure the app directory is owned by the non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Worker service does not expose an HTTP port — runs background jobs only.
# No HEALTHCHECK — health is determined by process liveness & job queues.

# ---------------------------------------------------------------
# Service owner: replace the CMD below with your entry point.
# Example: CMD ["python", "-m", "src.worker"]
# ---------------------------------------------------------------
CMD ["python", "-m", "src.main"]
