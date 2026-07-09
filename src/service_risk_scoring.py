"""Score synthetic service reliability risk on a 0-100 scale."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, ensure_project_dirs


def score_services(
    processed_dir: Path | None = None,
    predictions_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    ensure_project_dirs()
    processed = processed_dir or PROCESSED_DATA_DIR
    predictions = predictions_dir or PREDICTIONS_DIR
    raw = raw_dir or RAW_DATA_DIR

    metrics_df = pd.read_csv(processed / "service_hourly_metrics.csv")
    alerts_df = pd.read_csv(predictions / "reliability_alerts.csv")
    incidents_df = pd.read_csv(predictions / "incidents.csv")
    deployments_df = pd.read_csv(raw / "deployment_events.csv")

    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    deployments_df["timestamp"] = pd.to_datetime(deployments_df["timestamp"], utc=True)

    latest_hour = metrics_df["hour"].max()
    recent_metrics = metrics_df[metrics_df["hour"] >= latest_hour - pd.Timedelta(hours=24)]
    recent_alerts = alerts_df[alerts_df["timestamp"] >= latest_hour - pd.Timedelta(hours=48)]

    rows = []
    for service_name, service_metrics in recent_metrics.groupby("service_name"):
        alert_count = int((recent_alerts["service_name"] == service_name).sum())
        service_incidents = incidents_df[incidents_df["primary_service"] == service_name]
        incident_count = int(len(service_incidents))
        deployment_recency_hours = (
            latest_hour - deployments_df[deployments_df["service_name"] == service_name]["timestamp"].max()
        ).total_seconds() / 3600

        error_rate = float(service_metrics["error_rate"].mean())
        p95_latency = float(service_metrics["p95_latency_ms"].quantile(0.95))
        cpu_pressure = float(service_metrics["cpu_usage"].mean())
        memory_pressure = float(service_metrics["memory_usage"].mean())
        db_latency = float(service_metrics["db_latency_ms"].mean())
        queue_lag = float(service_metrics["queue_lag"].mean())

        score = min(
            100.0,
            (
                alert_count * 6
                + incident_count * 8
                + error_rate * 180
                + (p95_latency / 12)
                + (cpu_pressure * 0.25)
                + (memory_pressure * 0.25)
                + (db_latency * 0.18)
                + (queue_lag * 1.4)
                + (0 if deployment_recency_hours > 24 else 8)
            ),
        )
        risk_band = "Critical" if score >= 80 else "High" if score >= 60 else "Medium" if score >= 35 else "Low"
        rows.append(
            {
                "service_name": service_name,
                "risk_score": round(score, 2),
                "risk_band": risk_band,
                "recent_anomaly_count": alert_count,
                "recent_incident_count": incident_count,
                "recent_error_rate": round(error_rate, 4),
                "recent_p95_latency_ms": round(p95_latency, 2),
                "recent_cpu_usage": round(cpu_pressure, 2),
                "recent_memory_usage": round(memory_pressure, 2),
                "recent_db_latency_ms": round(db_latency, 2),
                "recent_queue_lag": round(queue_lag, 2),
                "deployment_recency_hours": round(deployment_recency_hours, 2),
            }
        )

    scores_df = pd.DataFrame(rows).sort_values(["risk_score", "service_name"], ascending=[False, True]).reset_index(drop=True)
    scores_df.to_csv(predictions / "service_risk_scores.csv", index=False)
    return scores_df


def main() -> None:
    scores_df = score_services()
    print("Service risk scores generated:", len(scores_df))


if __name__ == "__main__":
    main()
