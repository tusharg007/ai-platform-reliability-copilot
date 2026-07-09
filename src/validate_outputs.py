"""Fail fast when generated analytics outputs are empty or saturated."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import ASSETS_DIR, PREDICTIONS_DIR, PROCESSED_DATA_DIR, ROOT_DIR
from src.copilot import answer_question


def validate_outputs() -> None:
    metrics_df = pd.read_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
    alerts_df = pd.read_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
    incidents_df = pd.read_csv(PREDICTIONS_DIR / "incidents.csv")
    risk_df = pd.read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")

    required_risk_columns = {
        "service_name",
        "risk_score",
        "risk_band",
        "request_count",
        "error_rate",
        "p95_latency_ms",
        "anomaly_count",
        "high_critical_alert_count",
        "incident_count",
        "top_risk_driver_1",
        "top_risk_driver_2",
        "top_risk_driver_3",
        "recommended_action",
    }
    required_alert_columns = {
        "alert_id",
        "timestamp",
        "service_name",
        "severity",
        "alert_type",
        "anomaly_score",
        "metric_name",
        "metric_value",
        "baseline_value",
        "anomaly_reason",
        "suggested_investigation_area",
    }
    missing_risk = required_risk_columns - set(risk_df.columns)
    missing_alerts = required_alert_columns - set(alerts_df.columns)
    if missing_risk:
        raise ValueError(f"Missing risk score columns: {sorted(missing_risk)}")
    if missing_alerts:
        raise ValueError(f"Missing alert columns: {sorted(missing_alerts)}")

    if alerts_df.empty or incidents_df.empty:
        raise ValueError("alerts or incidents are empty")
    if risk_df["risk_score"].nunique() <= 1:
        raise ValueError("risk scores are all equal")
    if (risk_df["risk_score"] == 100).all():
        raise ValueError("risk scores are saturated at 100")
    if float(risk_df["risk_score"].max() - risk_df["risk_score"].min()) < 20:
        raise ValueError("risk score span is too small")
    if risk_df["risk_band"].nunique() < 3:
        raise ValueError("fewer than 3 risk bands were generated")
    if metrics_df["error_rate"].max() <= 0:
        raise ValueError("error rates are all zero")
    if alerts_df["alert_type"].nunique() < 3:
        raise ValueError("too few alert types were generated")

    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    recent_error_rates = metrics_df[metrics_df["hour"] >= metrics_df["hour"].max() - pd.Timedelta(hours=24)].groupby("service_name")["error_rate"].mean()
    if recent_error_rates.empty or recent_error_rates.sum() <= 0:
        raise ValueError("latest error rate chart would be empty")

    severity_counts = alerts_df["severity"].value_counts()
    if severity_counts.nunique() < 3:
        raise ValueError("fewer than 3 alert severity levels were generated")
    critical_count = int(severity_counts.get("critical", 0))
    medium_high_total = int(severity_counts.get("medium", 0) + severity_counts.get("high", 0))
    if critical_count > 0 and critical_count >= medium_high_total:
        raise ValueError("critical alerts dominate medium and high alerts")

    render_yaml = ROOT_DIR / "render.yaml"
    requirements_api = ROOT_DIR / "requirements-api.txt"
    render_start = ROOT_DIR / "scripts" / "render_start.sh"
    if not render_yaml.exists():
        raise ValueError("render.yaml is missing")
    if not requirements_api.exists():
        raise ValueError("requirements-api.txt is missing")
    if not render_start.exists():
        raise ValueError("scripts/render_start.sh is missing")
    render_text = render_yaml.read_text(encoding="utf-8")
    if "data/generate_synthetic_data.py" in render_text:
        raise ValueError("render.yaml still references deleted startup script")
    if "streamlit" in render_text.lower():
        raise ValueError("render.yaml should not start the Streamlit dashboard")
    if "frontend" in render_text.lower() or "backend" in render_text.lower():
        raise ValueError("render.yaml still contains stale frontend/backend references")

    response = answer_question("Why is payment-service risky in the latest synthetic incident window?")
    supporting = " ".join(response.get("Supporting evidence", []))
    for required_fragment in ["Risk score:", "24h error rate:", "P95 latency:", "Recent high/critical alert count:"]:
        if required_fragment not in supporting:
            raise ValueError("copilot response is missing concrete numeric evidence")

    required_assets = [
        "dashboard_overview.png",
        "service_health.png",
        "anomaly_detection.png",
        "incident_timeline.png",
        "copilot_assistant.png",
        "model_evaluation.png",
    ]
    for filename in required_assets:
        path = ASSETS_DIR / filename
        if not path.exists() or path.stat().st_size < 20000:
            raise ValueError(f"Missing or empty screenshot: {filename}")


def main() -> None:
    validate_outputs()
    print("Output validation passed.")


if __name__ == "__main__":
    main()
