"""FastAPI entry point for the AI Platform Reliability Copilot (v2.0 Production)."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.api.chat import router as chat_router
from backend.api.incidents import router as incidents_router
from backend.api.logs import router as logs_router
from backend.api.metrics import router as metrics_router
from backend.database.db import create_all_tables, initialize_database
from backend.ingestion import router as ingestion_router
from backend.services.log_analyzer import LogAnalyzer
from backend.services.redis_client import redis_info
from backend.telemetry import (
    configure_logging,
    get_logger,
    setup_otel,
)
from backend.utils.config import get_settings

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Application Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown lifecycle tasks."""
    logger.info(
        "Starting AI Platform Reliability Copilot",
        version=settings.app_version,
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        llm_model=settings.resolved_model_name,
    )
    setup_otel(app)

    db_result = initialize_database()
    logger.info("Database seeded", tables=db_result)
    await create_all_tables()

    # ── Redis probe ────────────────────────────────────────────────────────
    if settings.redis_enabled:
        from backend.services.redis_client import get_client, is_available
        get_client()  # Force initial connection
        if is_available():
            logger.info("Redis connected and ready")
        else:
            logger.warning("Redis is ENABLED but unreachable — running without cache")

    # ── Slack test ping (only on first startup, non-blocking) ─────────────
    if settings.slack_webhook_url:
        try:
            from backend.services.alerting import send_test_alert
            send_test_alert()
        except Exception as exc:
            logger.warning("Slack test ping failed: %s", exc)

    yield

    logger.info("Shutting down AI Platform Reliability Copilot")


# ─────────────────────────────────────────────────────────────────────────────
#  FastAPI Application
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    description=(
        "Production-grade platform reliability copilot with real-time anomaly detection, "
        "incident clustering, multi-dimensional risk scoring, runbook retrieval, "
        "and LLM-powered root-cause recommendations."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request Timing Middleware ─────────────────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next) -> Response:
    """Attach X-Process-Time header and record query duration metric."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat_router)
app.include_router(logs_router)
app.include_router(metrics_router)
app.include_router(incidents_router)
app.include_router(ingestion_router)


# ─────────────────────────────────────────────────────────────────────────────
#  Core Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
def health() -> dict:
    """Kubernetes readiness / liveness probe."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.resolved_model_name,
    }


@app.get("/metrics", tags=["ops"], include_in_schema=False)
def prometheus_metrics():
    """Prometheus metrics scrape endpoint.

    Returns OTel metrics in Prometheus text format.
    Active when OTEL_ENABLED=true (no external collector needed).
    """
    from fastapi.responses import Response

    from backend.telemetry import get_prometheus_metrics_response

    content, media_type = get_prometheus_metrics_response()
    if content is None:
        return Response(
            content="# OTel Prometheus exporter not initialised. Set OTEL_ENABLED=true\n",
            media_type="text/plain",
            status_code=503,
        )
    return Response(content=content, media_type=media_type)


@app.get("/services", tags=["ops"])
def services() -> dict:
    """Return the list of monitored microservices."""
    return {"services": LogAnalyzer().service_list()}


@app.get("/pipeline/status", tags=["ops"])
def pipeline_status() -> dict:
    """Return the status of the ingestion, cache, and telemetry pipeline."""
    from backend.ingestion import StreamProcessor
    processor = StreamProcessor.get()
    return {
        "pipeline": "active",
        "ingestion": processor.stats(),
        "otel_enabled": settings.otel_enabled,
        "kafka_enabled": settings.kafka_enabled,
        "redis": redis_info(),
        "slack_enabled": bool(settings.slack_webhook_url),
        "llm_provider": settings.llm_provider,
        "llm_model": settings.resolved_model_name,
        "database_url": settings.database_url.split("@")[-1],
    }

