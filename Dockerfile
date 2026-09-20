# ─────────────────────────────────────────────────────────────────
#  Multi-stage Dockerfile — AI Platform Reliability Copilot v2.0
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="AI Platform Reliability Copilot"
LABEL org.opencontainers.image.version="2.0.0"
LABEL org.opencontainers.image.description="Production-grade reliability copilot with anomaly detection, incident clustering, risk scoring, and LLM-powered root-cause analysis"

# Non-root user for security
RUN groupadd -r copilot && useradd -r -g copilot -s /bin/bash copilot

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY evals/ ./evals/
COPY knowledge_base/ ./knowledge_base/
COPY data/ ./data/

# Ensure data directory is writable by app user
RUN chown -R copilot:copilot /app

USER copilot

# Environment defaults (override via docker run -e or docker-compose)
ENV APP_ENV=production \
    LLM_PROVIDER=mock \
    LOG_FORMAT=json \
    LOG_LEVEL=INFO \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000 8501

# Default: run the backend API
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
