"""CSV-backed service layer for the FastAPI application."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import HTTPException

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR
from src.copilot import answer_question


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Required output missing: {path.name}. Run the pipeline first.")
    return pd.read_csv(path)


def overview_kpis() -> dict[str, object]:
    metrics_df = _read_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
    risk_df = _read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")
    incidents_df = _read_csv(PREDICTIONS_DIR / "incidents.csv")
    return {
        "services_monitored": int(metrics_df["service_name"].nunique()),
        "latest_average_error_rate": round(float(metrics_df.sort_values("hour").groupby("service_name").tail(1)["error_rate"].mean()), 4),
        "latest_average_p95_latency_ms": round(float(metrics_df.sort_values("hour").groupby("service_name").tail(1)["p95_latency_ms"].mean()), 2),
        "high_risk_services": int((risk_df["risk_band"].isin(["High", "Critical"])).sum()),
        "clustered_incidents": int(len(incidents_df)),
    }


def services_health() -> list[dict[str, object]]:
    return _read_csv(PREDICTIONS_DIR / "service_risk_scores.csv").to_dict(orient="records")


def high_risk_services() -> list[dict[str, object]]:
    df = _read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")
    return df[df["risk_band"].isin(["High", "Critical"])].to_dict(orient="records")


def recent_anomalies(limit: int = 25) -> list[dict[str, object]]:
    df = _read_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
    return df.sort_values("timestamp", ascending=False).head(limit).to_dict(orient="records")


def recent_incidents(limit: int = 20) -> list[dict[str, object]]:
    df = _read_csv(PREDICTIONS_DIR / "incidents.csv")
    return df.sort_values("start_time", ascending=False).head(limit).to_dict(orient="records")


def get_incident(incident_id: str) -> dict[str, object]:
    df = _read_csv(PREDICTIONS_DIR / "incidents.csv")
    match = df[df["incident_id"] == incident_id]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Incident not found: {incident_id}")
    return match.iloc[0].to_dict()


def ask_copilot(question: str | None = None, incident_id: str | None = None) -> dict[str, object]:
    return answer_question(question=question, incident_id=incident_id)


def summarize_incident(incident_id: str) -> dict[str, object]:
    incident = get_incident(incident_id)
    return {
        "incident_id": incident_id,
        "summary": f"{incident['primary_service']} experienced {incident['suspected_root_cause']} between {incident['start_time']} and {incident['end_time']}.",
        "evidence_summary": incident["evidence_summary"],
        "recommended_next_steps": str(incident["recommended_next_steps"]).split("; "),
    }


def predict_service_risk(service_name: str) -> dict[str, object]:
    df = _read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")
    match = df[df["service_name"] == service_name]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Service not found: {service_name}")
    return match.iloc[0].to_dict()


def load_evaluation_metrics() -> dict[str, object]:
    path = REPORTS_DIR / "metrics.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="metrics.json not found. Run evaluation first.")
    return pd.read_json(path, typ="series").to_dict()
