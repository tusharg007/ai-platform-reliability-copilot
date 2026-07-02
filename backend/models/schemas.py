"""Pydantic request and response contracts for the FastAPI service."""

from typing import Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    service_name: str | None = None
    region: str | None = None
    time_window: str | None = "last_2_hours"


class ChatResponse(BaseModel):
    answer: str
    evidence: list[str]
    sources: list[dict[str, Any]]
    recommended_actions: list[str]
    severity: str | None = None


class ServiceRegionRequest(BaseModel):
    service_name: str
    region: str | None = None


class AnomalyRequest(ServiceRegionRequest):
    metric_name: str | None = None


class LogAnalysisResponse(BaseModel):
    service_name: str | None
    region: str | None
    total_logs: int
    error_rate: float
    top_error_types: list[dict[str, Any]]
    latency_summary: dict[str, float]
    deployment_failures: list[dict[str, Any]]


class AnomalyResponse(BaseModel):
    service_name: str
    health_score: float
    anomalies: list[dict[str, Any]]


class IncidentResponse(BaseModel):
    service_name: str
    region: str | None
    summary: str
    root_cause_hypothesis: str
    action_plan: list[str]
    postmortem_template: str


class FeedbackRequest(BaseModel):
    query: str
    rating: int = Field(..., ge=1, le=5)
    comments: str | None = None
