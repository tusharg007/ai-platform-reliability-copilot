"""FastAPI entry point for the AI Platform Reliability Copilot."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.chat import router as chat_router
from backend.api.incidents import router as incidents_router
from backend.api.logs import router as logs_router
from backend.api.metrics import router as metrics_router
from backend.database.db import initialize_database
from backend.services.log_analyzer import LogAnalyzer
from backend.utils.config import get_settings


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="RAG, agentic log analytics, anomaly detection, and incident summaries for platform engineers.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(logs_router)
app.include_router(metrics_router)
app.include_router(incidents_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/services")
def services() -> dict:
    return {"services": LogAnalyzer().service_list()}


@app.on_event("startup")
def startup() -> None:
    initialize_database()
