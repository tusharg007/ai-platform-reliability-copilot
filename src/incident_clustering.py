"""Cluster correlated reliability alerts into incidents."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PREDICTIONS_DIR, RAW_DATA_DIR, ensure_project_dirs


CLUSTER_GAP_HOURS = 4


def cluster_incidents(predictions_dir: Path | None = None, raw_dir: Path | None = None) -> pd.DataFrame:
    ensure_project_dirs()
    prediction_root = predictions_dir or PREDICTIONS_DIR
    raw_root = raw_dir or RAW_DATA_DIR

    alerts_df = pd.read_csv(prediction_root / "reliability_alerts.csv")
    known_df = pd.read_csv(raw_root / "known_incidents.csv")
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    known_df["start_time"] = pd.to_datetime(known_df["start_time"], utc=True)
    known_df["end_time"] = pd.to_datetime(known_df["end_time"], utc=True)

    alerts_df["root_cause_key"] = alerts_df["alert_type"].replace(
        {
            "db_latency_spike": "database timeout",
            "deployment_regression": "deployment regression",
            "memory_pressure": "memory leak",
            "queue_backlog": "queue backlog",
            "auth_failure_spike": "authentication failure spike",
            "external_api_failure": "external API failure",
            "latency_spike": "high latency",
            "error_rate_spike": "5xx error spike",
        }
    )
    alerts_df = alerts_df.sort_values(["root_cause_key", "timestamp", "service_name"]).reset_index(drop=True)

    clusters: list[list[dict[str, object]]] = []
    current_cluster: list[dict[str, object]] = []
    current_end = None
    current_key = None
    current_deployment = None

    for row in alerts_df.to_dict(orient="records"):
        timestamp = pd.Timestamp(row["timestamp"])
        same_group = (
            current_key == row["root_cause_key"]
            and current_deployment == row["deployment_version"]
            and current_end is not None
            and timestamp <= current_end + pd.Timedelta(hours=CLUSTER_GAP_HOURS)
        )
        if same_group or not current_cluster:
            current_cluster.append(row)
            current_end = timestamp if current_end is None else max(current_end, timestamp)
            current_key = row["root_cause_key"]
            current_deployment = row["deployment_version"]
        else:
            clusters.append(current_cluster)
            current_cluster = [row]
            current_end = timestamp
            current_key = row["root_cause_key"]
            current_deployment = row["deployment_version"]
    if current_cluster:
        clusters.append(current_cluster)

    incident_rows = []
    for cluster_index, cluster in enumerate(clusters, start=1):
        incident_rows.append(build_incident(cluster_index, cluster, known_df))

    incidents_df = pd.DataFrame(incident_rows).sort_values("start_time").reset_index(drop=True)
    if incidents_df.empty:
        raise ValueError("Incident clustering produced no incidents")
    incidents_df.to_csv(prediction_root / "incidents.csv", index=False)
    return incidents_df


def build_incident(cluster_index: int, cluster: list[dict[str, object]], known_df: pd.DataFrame) -> dict[str, object]:
    cluster_df = pd.DataFrame(cluster)
    start_time = pd.to_datetime(cluster_df["timestamp"], utc=True).min()
    end_time = pd.to_datetime(cluster_df["timestamp"], utc=True).max()
    alert_count = int(len(cluster_df))
    severity = summarize_severity(cluster_df["severity"].tolist())
    primary_service = str(cluster_df["service_name"].value_counts().idxmax())
    affected_services = sorted(cluster_df["service_name"].unique().tolist())
    symptoms = sorted(cluster_df["alert_type"].unique().tolist())
    root_cause = str(cluster_df["root_cause_key"].mode().iloc[0])
    deployment_version = str(cluster_df["deployment_version"].mode().iloc[0])

    matching_known = known_df[
        (known_df["start_time"] <= end_time)
        & (known_df["end_time"] >= start_time)
        & (known_df["affected_services"].str.contains(primary_service))
    ]
    if not matching_known.empty:
        matched = matching_known.iloc[0]
        root_cause = str(matched["incident_type"])
        if primary_service not in str(matched["affected_services"]).split(","):
            primary_service = str(matched["primary_service"])

    evidence_summary = (
        f"{alert_count} alerts across {len(affected_services)} services from {start_time.isoformat()} to {end_time.isoformat()}. "
        f"Dominant symptoms: {', '.join(symptoms[:4])}. Deployment context: {deployment_version}."
    )
    return {
        "incident_id": f"INC-CLUSTER-{cluster_index:03d}",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "primary_service": primary_service,
        "affected_services": ", ".join(affected_services),
        "severity": severity,
        "alert_count": alert_count,
        "symptoms": ", ".join(symptoms),
        "suspected_root_cause": root_cause,
        "evidence_summary": evidence_summary,
        "recommended_next_steps": "; ".join(recommend_next_steps(root_cause)),
    }


def summarize_severity(severities: list[str]) -> str:
    if "critical" in severities:
        return "critical"
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    return "low"


def recommend_next_steps(root_cause: str) -> list[str]:
    if "database" in root_cause:
        return [
            "Inspect slow queries, connection pool usage, and timeout propagation.",
            "Validate rollback criteria for dependent services if the failure remains customer-impacting.",
        ]
    if "deployment" in root_cause:
        return [
            "Diff the rollout against the last stable build and verify the change window.",
            "Rollback or disable the suspect change if regression signals remain elevated.",
        ]
    if "memory" in root_cause:
        return [
            "Inspect memory growth over time and recent cache or model changes.",
            "Confirm whether restart behavior masked the underlying leak before escalation.",
        ]
    if "queue" in root_cause:
        return [
            "Measure consumer throughput, retry storms, and queue drain time.",
            "Check downstream provider latency that may be amplifying queue lag.",
        ]
    if "auth" in root_cause:
        return [
            "Inspect session expiry, token validation, and regional identity-provider latency.",
            "Confirm whether any auth-related rollout preceded the spike.",
        ]
    if "external API" in root_cause:
        return [
            "Check provider status, retry policy, and circuit-breaker behavior.",
            "Verify whether fallback paths or queuing strategies are working as expected.",
        ]
    return [
        "Correlate the cluster against logs, traces, and recent releases.",
        "Escalate for human review before taking irreversible mitigation steps.",
    ]


def main() -> None:
    incidents_df = cluster_incidents()
    print("Clustered incidents:", len(incidents_df))


if __name__ == "__main__":
    main()
