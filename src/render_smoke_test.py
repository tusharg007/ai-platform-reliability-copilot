"""Render-safe smoke test that avoids matplotlib, Streamlit, and dashboard code."""

from __future__ import annotations

import pandas as pd

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR


def main() -> None:
    metrics_path = PROCESSED_DATA_DIR / "service_hourly_metrics.csv"
    alerts_path = PREDICTIONS_DIR / "reliability_alerts.csv"
    incidents_path = PREDICTIONS_DIR / "incidents.csv"
    risks_path = PREDICTIONS_DIR / "service_risk_scores.csv"

    metrics_df = pd.read_csv(metrics_path)
    alerts_df = pd.read_csv(alerts_path)
    incidents_df = pd.read_csv(incidents_path)
    risk_df = pd.read_csv(risks_path)

    if metrics_df.empty or alerts_df.empty or incidents_df.empty or risk_df.empty:
        raise ValueError("Render smoke test found empty analytics outputs")
    if {"service_name", "error_rate", "p95_latency_ms"} - set(metrics_df.columns):
        raise ValueError("Render smoke test found missing metrics columns")
    if {"alert_id", "severity", "alert_type"} - set(alerts_df.columns):
        raise ValueError("Render smoke test found missing alert columns")
    if {"incident_id", "primary_service"} - set(incidents_df.columns):
        raise ValueError("Render smoke test found missing incident columns")
    if {"service_name", "risk_score", "risk_band"} - set(risk_df.columns):
        raise ValueError("Render smoke test found missing risk score columns")
    if risk_df["risk_score"].nunique() <= 1:
        raise ValueError("Render smoke test found collapsed risk scores")
    if float(risk_df["risk_score"].max() - risk_df["risk_score"].min()) < 20:
        raise ValueError("Render smoke test found insufficient risk score spread")
    if risk_df["risk_band"].nunique() < 3:
        raise ValueError("Render smoke test found insufficient risk band diversity")
    print("Render smoke test passed.")


if __name__ == "__main__":
    main()
