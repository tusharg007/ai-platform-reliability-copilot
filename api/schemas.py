"""API schemas for the production-oriented reliability prototype."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CopilotAskRequest(BaseModel):
    question: str | None = None
    incident_id: str | None = None


class CopilotAskResponse(BaseModel):
    response: dict[str, Any]


class IncidentSummarizeRequest(BaseModel):
    incident_id: str


class PredictRiskRequest(BaseModel):
    service_name: str


class HealthResponse(BaseModel):
    status: str
    project: str


class RiskPredictionResponse(BaseModel):
    service_name: str
    risk_score: float
    risk_band: str
