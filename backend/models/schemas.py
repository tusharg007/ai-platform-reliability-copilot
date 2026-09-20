"""Pydantic request/response contracts for the AI Platform Reliability Copilot (v2.0)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
#  Shared Base Models
# ─────────────────────────────────────────────────────────────────────────────

class ServiceRegionRequest(BaseModel):
    service_name: str
    region: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
#  Chat / Copilot
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    service_name: str | None = None
    region: str | None = None
    time_window: str | None = "last_2_hours"
    session_id: str | None = None   # For conversation memory


class CausalStep(BaseModel):
    sequence: int
    event: str
    evidence: str
    timestamp_hint: str = ""


class ChatResponse(BaseModel):
    answer: str
    evidence: list[str]
    sources: list[dict[str, Any]]
    recommended_actions: list[str]
    severity: str | None = None
    risk_score: float | None = None
    confidence: float | None = None
    estimated_mttr_minutes: int | None = None
    causal_chain: list[dict[str, Any]] = Field(default_factory=list)
    generation_method: str = "deterministic"
    latency_ms: float | None = None


# ─────────────────────────────────────────────────────────────────────────────
#  Log Analytics
# ─────────────────────────────────────────────────────────────────────────────

class LogAnalysisResponse(BaseModel):
    service_name: str | None
    region: str | None
    total_logs: int
    error_rate: float
    top_error_types: list[dict[str, Any]]
    latency_summary: dict[str, float]
    deployment_failures: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
#  Anomaly Detection
# ─────────────────────────────────────────────────────────────────────────────

class AnomalyRequest(ServiceRegionRequest):
    metric_name: str | None = None


class AnomalyResponse(BaseModel):
    service_name: str
    health_score: float
    anomalies: list[dict[str, Any]]
    high_count: int = 0
    medium_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
#  Risk Scoring
# ─────────────────────────────────────────────────────────────────────────────

class RiskScoreRequest(BaseModel):
    service_name: str
    region: str | None = None
    error_type: str | None = None


class RiskScoreResponse(BaseModel):
    service_name: str
    region: str | None
    error_type: str | None
    blast_radius_score: float
    velocity_score: float
    slo_burn_score: float
    historical_score: float
    revenue_score: float
    composite_score: float
    severity: str
    contributing_factors: list[str]
    calculated_at: str


class FleetRiskResponse(BaseModel):
    fleet_risk_score: float
    fleet_severity: str
    highest_risk_service: str
    highest_risk_score: float
    services_by_severity: dict[str, list[str]]
    per_service_risk: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
#  Incident Clustering
# ─────────────────────────────────────────────────────────────────────────────

class ClusterRequest(BaseModel):
    window_hours: int = Field(default=4, ge=1, le=72)


class ClusterResponse(BaseModel):
    clusters: list[dict[str, Any]]
    unclustered: list[dict[str, Any]]
    total_signals: int
    blast_radius_summary: dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
#  Root-Cause Analysis
# ─────────────────────────────────────────────────────────────────────────────

class RCARequest(ServiceRegionRequest):
    pass


class RCAResponse(BaseModel):
    service_name: str
    region: str | None
    causal_chain: list[dict[str, Any]]
    root_cause: str
    confidence: float
    evidence: list[str]
    recommended_actions: list[str]
    runbook_references: list[str]
    estimated_mttr_minutes: int
    severity: str
    risk_score: float
    generation_method: str
    generated_at: str


# ─────────────────────────────────────────────────────────────────────────────
#  Incident Summary
# ─────────────────────────────────────────────────────────────────────────────

class IncidentResponse(BaseModel):
    service_name: str
    region: str | None
    summary: str
    root_cause_hypothesis: str
    action_plan: list[str]
    postmortem_template: str


# ─────────────────────────────────────────────────────────────────────────────
#  Dashboard KPIs
# ─────────────────────────────────────────────────────────────────────────────

class DashboardKPIResponse(BaseModel):
    """Real-time KPIs for the top-level dashboard."""
    total_services: int
    healthy_services: int
    degraded_services: int
    critical_services: int
    average_latency_ms: float
    p95_latency_ms: float
    overall_error_rate: float
    most_affected_region: str
    active_incident_count: int
    fleet_risk_score: float
    fleet_severity: str


# ─────────────────────────────────────────────────────────────────────────────
#  Feedback
# ─────────────────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    query: str
    answer: str | None = None
    rating: int = Field(..., ge=1, le=5)
    comments: str | None = None
    session_id: str | None = None
    service_name: str | None = None
