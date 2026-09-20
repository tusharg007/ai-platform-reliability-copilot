"""Production metrics API: anomaly detection, risk scoring, KPIs, and fleet health."""

from fastapi import APIRouter

from backend.models.schemas import (
    AnomalyRequest,
    AnomalyResponse,
    ClusterRequest,
    ClusterResponse,
    DashboardKPIResponse,
    FleetRiskResponse,
    RCARequest,
    RCAResponse,
    RiskScoreRequest,
    RiskScoreResponse,
)
from backend.services.anomaly_detector import AnomalyDetector
from backend.services.incident_clustering import IncidentClusterer
from backend.services.log_analyzer import LogAnalyzer
from backend.services.risk_scorer import RiskScorer
from backend.services.root_cause_engine import RootCauseEngine

router = APIRouter()


# ── Existing Endpoints (preserved, extended) ──────────────────────────────────

@router.get("/metrics/summary")
def metrics_summary() -> dict:
    """Fleet-wide telemetry summary with Golden Signal KPIs."""
    return LogAnalyzer().metrics_summary()


@router.post("/detect-anomalies", response_model=AnomalyResponse)
def detect_anomalies(request: AnomalyRequest) -> AnomalyResponse:
    """Ensemble anomaly detection with health score."""
    detector = AnomalyDetector()
    anomaly_list = detector.detect(request.service_name, request.metric_name, request.region)
    return AnomalyResponse(
        service_name=request.service_name,
        health_score=detector.get_service_health_score(request.service_name, request.region),
        anomalies=anomaly_list,
        high_count=sum(1 for a in anomaly_list if a["severity"] == "high"),
        medium_count=sum(1 for a in anomaly_list if a["severity"] == "medium"),
    )


# ── New Endpoints ─────────────────────────────────────────────────────────────

@router.post("/risk-score", response_model=RiskScoreResponse)
def risk_score(request: RiskScoreRequest) -> RiskScoreResponse:
    """Compute multi-dimensional risk score for a service incident.

    Returns blast_radius, velocity, SLO_burn, historical, and revenue
    dimension scores alongside the composite severity classification.
    """
    assessment = RiskScorer().score_incident(
        request.service_name, request.region, request.error_type
    )
    return RiskScoreResponse(**assessment.to_dict())


@router.get("/fleet-risk", response_model=FleetRiskResponse)
def fleet_risk() -> FleetRiskResponse:
    """Fleet-wide risk summary: per-service risk scores and severity distribution."""
    return FleetRiskResponse(**RiskScorer().fleet_risk_summary())


@router.post("/cluster-incidents", response_model=ClusterResponse)
def cluster_incidents(request: ClusterRequest) -> ClusterResponse:
    """Cluster active incident signals using HDBSCAN.

    Groups related failures by embedding similarity to identify correlated
    outages and coordinated deployment regressions.
    """
    result = IncidentClusterer().full_clustering_analysis(request.window_hours)
    return ClusterResponse(**result)


@router.post("/root-cause", response_model=RCAResponse)
def root_cause_analysis(request: RCARequest) -> RCAResponse:
    """Full LLM-powered root-cause analysis with causal chain reasoning.

    Synthesises evidence from log analytics, anomaly detection, RAG runbooks,
    and risk scoring into a structured root-cause report.
    """
    scorer = RiskScorer()
    risk = scorer.score_incident(request.service_name, request.region)
    rca = RootCauseEngine().analyze(request.service_name, request.region, risk_assessment=risk)
    return RCAResponse(**rca.to_dict())


@router.get("/dashboard/kpis", response_model=DashboardKPIResponse)
def dashboard_kpis() -> DashboardKPIResponse:
    """Real-time KPIs for the top-level dashboard.

    Returns service health counts, latency/error KPIs, active incident count,
    and fleet risk score — all in a single request for efficient dashboard loading.
    """
    log_analyzer = LogAnalyzer()
    risk_scorer = RiskScorer()

    metrics = log_analyzer.metrics_summary()
    kpis = metrics.get("kpis", {})
    fleet = risk_scorer.fleet_risk_summary()

    # Count services by severity
    severity_groups = fleet["services_by_severity"]
    critical = len(severity_groups.get("SEV-1", [])) + len(severity_groups.get("SEV-2", []))
    degraded = len(severity_groups.get("SEV-3", []))
    total = kpis.get("total_services", 0)
    healthy = max(0, total - critical - degraded)

    return DashboardKPIResponse(
        total_services=total,
        healthy_services=healthy,
        degraded_services=degraded,
        critical_services=critical,
        average_latency_ms=kpis.get("average_latency", 0.0),
        p95_latency_ms=kpis.get("p95_latency", 0.0),
        overall_error_rate=kpis.get("overall_error_rate", 0.0),
        most_affected_region=kpis.get("most_affected_region", "unknown"),
        active_incident_count=critical,
        fleet_risk_score=fleet["fleet_risk_score"],
        fleet_severity=fleet["fleet_severity"],
    )
