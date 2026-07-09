"""FastAPI app exposing reliability analytics outputs."""

from __future__ import annotations

from fastapi import FastAPI

from api.schemas import CopilotAskRequest, CopilotAskResponse, HealthResponse, IncidentSummarizeRequest, PredictRiskRequest
from api import services


app = FastAPI(
    title="AI Platform Reliability Copilot",
    version="2.0.0",
    description="Production-oriented prototype for AI-assisted reliability analytics, anomaly detection, and incident intelligence.",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", project="AI Platform Reliability Copilot")


@app.get("/kpis/overview")
def kpis_overview() -> dict[str, object]:
    return services.overview_kpis()


@app.get("/services/health")
def service_health() -> list[dict[str, object]]:
    return services.services_health()


@app.get("/services/high-risk")
def service_high_risk() -> list[dict[str, object]]:
    return services.high_risk_services()


@app.get("/anomalies/recent")
def anomalies_recent() -> list[dict[str, object]]:
    return services.recent_anomalies()


@app.get("/incidents/recent")
def incidents_recent() -> list[dict[str, object]]:
    return services.recent_incidents()


@app.get("/incidents/{incident_id}")
def incident_detail(incident_id: str) -> dict[str, object]:
    return services.get_incident(incident_id)


@app.post("/copilot/ask", response_model=CopilotAskResponse)
def copilot_ask(request: CopilotAskRequest) -> CopilotAskResponse:
    return CopilotAskResponse(response=services.ask_copilot(request.question, request.incident_id))


@app.post("/incidents/summarize")
def incidents_summarize(request: IncidentSummarizeRequest) -> dict[str, object]:
    return services.summarize_incident(request.incident_id)


@app.post("/predict/service-risk")
def predict_service_risk(request: PredictRiskRequest) -> dict[str, object]:
    return services.predict_service_risk(request.service_name)
