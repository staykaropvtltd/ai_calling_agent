# ============================================
# STAYKARO AI CALLER — API Service
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
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


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
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (preserves layer caching)
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Application code
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

# Ensure the app directory is owned by the non-root user
RUN chown -R appuser:appuser /app && chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER appuser

# Health check — assumes /health endpoint exists
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
