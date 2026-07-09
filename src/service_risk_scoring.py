"""Calibrated service reliability risk scoring."""

from __future__ import annotations

from pathlib import Path
import math

import pandas as pd

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, ensure_project_dirs


SERVICE_CRITICALITY = {
    "api-gateway": 1.15,
    "auth-service": 0.95,
    "payment-service": 1.25,
    "recommendation-service": 0.90,
    "database-service": 1.20,
    "worker-service": 1.00,
    "notification-service": 0.85,
}


def score_services(processed_dir: Path | None = None, predictions_dir: Path | None = None) -> pd.DataFrame:
    ensure_project_dirs()
    processed_root = processed_dir or PROCESSED_DATA_DIR
    prediction_root = predictions_dir or PREDICTIONS_DIR

    metrics_df = pd.read_csv(processed_root / "service_hourly_metrics.csv")
    alerts_df = pd.read_csv(prediction_root / "reliability_alerts.csv")
    incidents_df = pd.read_csv(prediction_root / "incidents.csv")

    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)

    latest_hour = metrics_df["hour"].max()
    recent_metrics = metrics_df[metrics_df["hour"] >= latest_hour - pd.Timedelta(hours=48)]
    recent_alerts = alerts_df[alerts_df["timestamp"] >= latest_hour - pd.Timedelta(hours=72)]
    recent_incidents = incidents_df[incidents_df["start_time"] >= latest_hour - pd.Timedelta(days=7)]

    rows = []
    for service_name, service_metrics in recent_metrics.groupby("service_name"):
        service_alerts = recent_alerts[recent_alerts["service_name"] == service_name]
        service_incidents = recent_incidents[
            recent_incidents["primary_service"].eq(service_name)
            | recent_incidents["affected_services"].str.contains(service_name, na=False)
        ]
        rows.append(
            {
                "service_name": service_name,
                "request_count": int(service_metrics["request_count"].sum()),
                "error_rate": float(service_metrics["error_rate"].mean()),
                "p95_latency_ms": float(service_metrics["p95_latency_ms"].quantile(0.95)),
                "memory_pressure": float(service_metrics["avg_memory_usage"].quantile(0.9)),
                "cpu_pressure": float(service_metrics["avg_cpu_usage"].quantile(0.9)),
                "db_latency_ms": float(service_metrics["avg_db_latency_ms"].quantile(0.9)),
                "queue_lag": float(service_metrics["avg_queue_lag"].quantile(0.9)),
                "anomaly_count": int(len(service_alerts)),
                "high_critical_alert_count": int(service_alerts["severity"].isin(["high", "critical"]).sum()),
                "incident_count": int(len(service_incidents)),
                "deployment_recency_hours": float((latest_hour - service_metrics["hour"].max()).total_seconds() / 3600),
                "criticality_weight": SERVICE_CRITICALITY[service_name],
            }
        )

    scores_df = pd.DataFrame(rows)
    component_frame = pd.DataFrame(
        {
            "error_rate_component": percentile_scale(scores_df["error_rate"]),
            "latency_component": percentile_scale(scores_df["p95_latency_ms"]),
            "anomaly_component": percentile_scale(scores_df["anomaly_count"]),
            "high_alert_component": percentile_scale(scores_df["high_critical_alert_count"]),
            "incident_component": percentile_scale(scores_df["incident_count"]),
            "memory_component": percentile_scale(scores_df["memory_pressure"]),
            "cpu_component": percentile_scale(scores_df["cpu_pressure"]),
            "db_component": percentile_scale(scores_df["db_latency_ms"]),
            "queue_component": percentile_scale(scores_df["queue_lag"]),
            "criticality_component": min_max_scale(scores_df["criticality_weight"]),
        }
    )

    weighted = (
        component_frame["error_rate_component"] * 0.18
        + component_frame["latency_component"] * 0.16
        + component_frame["anomaly_component"] * 0.12
        + component_frame["high_alert_component"] * 0.11
        + component_frame["incident_component"] * 0.10
        + component_frame["memory_component"] * 0.09
        + component_frame["cpu_component"] * 0.07
        + component_frame["db_component"] * 0.09
        + component_frame["queue_component"] * 0.05
        + component_frame["criticality_component"] * 0.03
    )
    scores_df["risk_score"] = (18 + weighted * 76).clip(12, 94).round(2)
    scores_df["risk_band"] = scores_df["risk_score"].apply(risk_band)

    drivers = []
    for idx, row in scores_df.iterrows():
        service_components = {
            "error rate": component_frame.loc[idx, "error_rate_component"] * 0.18,
            "p95 latency": component_frame.loc[idx, "latency_component"] * 0.16,
            "anomaly count": component_frame.loc[idx, "anomaly_component"] * 0.12,
            "high severity alerts": component_frame.loc[idx, "high_alert_component"] * 0.11,
            "incident count": component_frame.loc[idx, "incident_component"] * 0.10,
            "memory pressure": component_frame.loc[idx, "memory_component"] * 0.09,
            "CPU pressure": component_frame.loc[idx, "cpu_component"] * 0.07,
            "DB latency": component_frame.loc[idx, "db_component"] * 0.09,
            "queue lag": component_frame.loc[idx, "queue_component"] * 0.05,
        }
        ordered = sorted(service_components.items(), key=lambda item: item[1], reverse=True)
        drivers.append([item[0] for item in ordered[:3]])
    scores_df["top_risk_driver_1"] = [items[0] for items in drivers]
    scores_df["top_risk_driver_2"] = [items[1] for items in drivers]
    scores_df["top_risk_driver_3"] = [items[2] for items in drivers]
    scores_df["recommended_action"] = scores_df["top_risk_driver_1"].apply(recommended_action)

    scores_df = scores_df[
        [
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
        ]
    ].sort_values(["risk_score", "service_name"], ascending=[False, True]).reset_index(drop=True)

    if scores_df["risk_score"].nunique() == 1:
        raise ValueError("risk scores collapsed to a single value")
    scores_df.to_csv(prediction_root / "service_risk_scores.csv", index=False)
    return scores_df


def percentile_scale(series: pd.Series) -> pd.Series:
    if series.nunique() <= 1:
        return pd.Series([0.5] * len(series), index=series.index)
    return series.rank(method="average", pct=True)


def min_max_scale(series: pd.Series) -> pd.Series:
    if series.nunique() <= 1:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - series.min()) / (series.max() - series.min())


def risk_band(score: float) -> str:
    if score >= 78:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def recommended_action(driver: str) -> str:
    if driver == "DB latency":
        return "Inspect slow queries and upstream timeout amplification."
    if driver == "queue lag":
        return "Increase worker throughput only after checking retry storms and provider latency."
    if driver == "error rate":
        return "Inspect high-impact failures, dependency health, and customer-facing error slices."
    if driver == "memory pressure":
        return "Review memory growth by release and consider rollback criteria."
    if driver == "p95 latency":
        return "Compare the latest release against previous latency baselines and slow endpoints."
    return "Review the dominant risk drivers before selecting mitigation steps."


def main() -> None:
    scores_df = score_services()
    print("Service risk scores generated:", len(scores_df))


if __name__ == "__main__":
    main()
