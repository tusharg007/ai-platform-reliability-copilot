"""Cluster nearby anomalies into reliability incidents."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, ensure_project_dirs


CLUSTER_GAP_HOURS = 3


def cluster_incidents(
    processed_dir: Path | None = None,
    predictions_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    ensure_project_dirs()
    source_predictions = predictions_dir or PREDICTIONS_DIR
    source_processed = processed_dir or PROCESSED_DATA_DIR
    source_raw = raw_dir or RAW_DATA_DIR

    alerts_df = pd.read_csv(source_predictions / "reliability_alerts.csv")
    metrics_df = pd.read_csv(source_processed / "service_hourly_metrics.csv")
    known_df = pd.read_csv(source_raw / "known_incidents.csv")

    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    known_df["start_time"] = pd.to_datetime(known_df["start_time"], utc=True)
    known_df["end_time"] = pd.to_datetime(known_df["end_time"], utc=True)
    alerts_df = alerts_df.sort_values(["service_name", "timestamp"]).reset_index(drop=True)

    incidents = []
    cluster_id = 1
    for service_name, service_alerts in alerts_df.groupby("service_name"):
        current_cluster: list[dict[str, object]] = []
        current_end = None
        for row in service_alerts.to_dict(orient="records"):
            timestamp = pd.Timestamp(row["timestamp"])
            if current_end is None or timestamp <= current_end + pd.Timedelta(hours=CLUSTER_GAP_HOURS):
                current_cluster.append(row)
                current_end = timestamp if current_end is None else max(current_end, timestamp)
            else:
                incidents.append(build_incident_record(cluster_id, current_cluster, metrics_df, known_df))
                cluster_id += 1
                current_cluster = [row]
                current_end = timestamp
        if current_cluster:
            incidents.append(build_incident_record(cluster_id, current_cluster, metrics_df, known_df))
            cluster_id += 1

    incidents_df = pd.DataFrame(incidents).sort_values("start_time").reset_index(drop=True)
    incidents_df.to_csv(source_predictions / "incidents.csv", index=False)
    return incidents_df


def build_incident_record(
    cluster_id: int,
    alerts: list[dict[str, object]],
    metrics_df: pd.DataFrame,
    known_df: pd.DataFrame,
) -> dict[str, object]:
    alert_df = pd.DataFrame(alerts)
    start_time = pd.to_datetime(alert_df["timestamp"]).min()
    end_time = pd.to_datetime(alert_df["timestamp"]).max()
    primary_service = str(alert_df["service_name"].mode().iloc[0])
    affected_services = sorted(alert_df["service_name"].unique().tolist())
    severity = summarize_severity(alert_df["severity"].tolist())
    symptoms = sorted(alert_df["alert_type"].unique().tolist())

    matching_known = known_df[
        (known_df["primary_service"] == primary_service)
        & (known_df["start_time"] <= end_time)
        & (known_df["end_time"] >= start_time)
    ]
    suspected_root_cause = (
        str(matching_known.iloc[0]["incident_type"])
        if not matching_known.empty
        else str(alert_df["alert_type"].mode().iloc[0])
    )

    metric_slice = metrics_df[
        (metrics_df["service_name"] == primary_service)
        & (pd.to_datetime(metrics_df["hour"], utc=True) >= start_time - pd.Timedelta(hours=1))
        & (pd.to_datetime(metrics_df["hour"], utc=True) <= end_time + pd.Timedelta(hours=1))
    ]
    if metric_slice.empty:
        evidence_summary = "Metrics unavailable for clustered window."
    else:
        evidence_summary = (
            f"Peak p95 latency {metric_slice['p95_latency_ms'].max():.1f} ms, "
            f"peak error rate {metric_slice['error_rate'].max() * 100:.2f}%, "
            f"peak queue lag {metric_slice['queue_lag'].max():.1f}, "
            f"peak DB latency {metric_slice['db_latency_ms'].max():.1f} ms."
        )

    next_steps = recommend_next_steps(suspected_root_cause)
    return {
        "incident_id": f"INC-CLUSTER-{cluster_id:03d}",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "primary_service": primary_service,
        "affected_services": ", ".join(affected_services),
        "severity": severity,
        "symptoms": ", ".join(symptoms),
        "suspected_root_cause": suspected_root_cause,
        "evidence_summary": evidence_summary,
        "recommended_next_steps": "; ".join(next_steps),
    }


def summarize_severity(severities: list[str]) -> str:
    if "critical" in severities:
        return "critical"
    if "high" in severities:
        return "high"
    return "medium"


def recommend_next_steps(root_cause: str) -> list[str]:
    if "database" in root_cause:
        return [
            "Inspect database slow query patterns and connection pool exhaustion.",
            "Check upstream timeout budgets and retry amplification.",
        ]
    if "memory" in root_cause:
        return [
            "Review memory growth over the incident window.",
            "Compare release changes touching caches, models, or data structures.",
        ]
    if "queue" in root_cause:
        return [
            "Measure consumer throughput and retry backlog growth.",
            "Inspect downstream provider health and dead-letter volume.",
        ]
    if "deployment" in root_cause:
        return [
            "Diff deployment config and application release notes.",
            "Rollback or disable the suspected change behind a feature flag if available.",
        ]
    return [
        "Correlate the incident against recent releases and dependency health.",
        "Review representative traces and high-severity logs before mitigation.",
    ]


def main() -> None:
    incidents_df = cluster_incidents()
    print("Clustered incidents:", len(incidents_df))


if __name__ == "__main__":
    main()
