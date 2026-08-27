# ============================================
# STAYKARO AI CALLER — Voice Gateway Service
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
        build-essential \
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
# - espeak-ng: pyttsx3's Linux TTS backend (Phase 5) — SAPI5/nsss aren't
#   available outside Windows/macOS, pyttsx3 falls back to espeak-ng here.
# - libgomp1: OpenMP runtime faster-whisper's CTranslate2 backend needs.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        espeak-ng \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (preserves layer caching)
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Application code
COPY src/ ./src/

# Gateway modules required by src/main.py (exotel router, internal calls
# client, dev routing, Pipecat voice pipeline, Phase 5 STT/AI/TTS pipeline)
COPY exotel_routes.py internal_calls.py dev_routing.py voice_pipeline.py \
     conversation.py stt_provider.py ai_provider.py tts_provider.py ./

# Ensure the app directory is owned by the non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check — assumes /health endpoint exists. start-period is generous
# because LocalWhisperSTTProvider (Phase 5) downloads/loads its model at
# import time — a one-time ~20-30s cost on first container start (cached in
# the image layer/HF cache on subsequent starts of the same container).
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:9000/health || exit 1

EXPOSE 9000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "9000"]
