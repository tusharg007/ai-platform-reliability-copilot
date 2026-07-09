"""Normalize raw logs and build service-hourly reliability metrics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR, REPORTS_DIR, ensure_project_dirs


REQUIRED_COLUMNS = [
    "timestamp",
    "service_name",
    "environment",
    "log_level",
    "request_id",
    "trace_id",
    "endpoint",
    "status_code",
    "latency_ms",
    "error_type",
    "message",
    "cpu_usage",
    "memory_usage",
    "db_latency_ms",
    "queue_lag",
    "region",
    "deployment_version",
]


def ingest_logs(raw_dir: Path | None = None, processed_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    ensure_project_dirs()
    source_dir = raw_dir or RAW_DATA_DIR
    target_dir = processed_dir or PROCESSED_DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    logs_df = pd.read_csv(source_dir / "platform_logs.csv")
    incidents_df = pd.read_csv(source_dir / "known_incidents.csv")

    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(logs_df.columns))
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    logs_df["timestamp"] = pd.to_datetime(logs_df["timestamp"], utc=True)
    logs_df = logs_df.sort_values("timestamp").reset_index(drop=True)
    logs_df["hour"] = logs_df["timestamp"].dt.floor("h")
    logs_df["error_type"] = logs_df["error_type"].fillna("")
    logs_df["message"] = logs_df["message"].fillna("")

    logs_df["is_error"] = logs_df["status_code"] >= 500
    logs_df["is_4xx"] = logs_df["status_code"].between(400, 499)
    logs_df["is_5xx"] = logs_df["status_code"] >= 500
    logs_df["is_auth_failure"] = logs_df["status_code"].isin([401, 403])

    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)
    incidents_df["end_time"] = pd.to_datetime(incidents_df["end_time"], utc=True)
    incidents_df["affected_service_list"] = incidents_df["affected_services"].str.split(",")

    logs_df["known_incident_flag"] = False
    logs_df["incident_label"] = ""
    for incident in incidents_df.to_dict(orient="records"):
        mask = (
            logs_df["service_name"].isin(incident["affected_service_list"])
            & (logs_df["region"] == incident["region"])
            & (logs_df["timestamp"] >= incident["start_time"])
            & (logs_df["timestamp"] <= incident["end_time"])
        )
        logs_df.loc[mask, "known_incident_flag"] = True
        logs_df.loc[mask, "incident_label"] = str(incident["incident_type"])

    grouped = logs_df.groupby(["hour", "service_name"], as_index=False)
    metrics_df = grouped.agg(
        request_count=("request_id", "count"),
        error_count=("is_error", "sum"),
        avg_latency_ms=("latency_ms", "mean"),
        p95_latency_ms=("latency_ms", lambda series: series.quantile(0.95)),
        avg_cpu_usage=("cpu_usage", "mean"),
        avg_memory_usage=("memory_usage", "mean"),
        avg_db_latency_ms=("db_latency_ms", "mean"),
        avg_queue_lag=("queue_lag", "mean"),
        status_5xx_rate=("is_5xx", "mean"),
        status_4xx_rate=("is_4xx", "mean"),
        auth_failure_rate=("is_auth_failure", "mean"),
        known_incident_flag=("known_incident_flag", "max"),
        region=("region", lambda values: values.mode().iloc[0]),
        deployment_version=("deployment_version", lambda values: values.mode().iloc[0]),
        incident_label=("incident_label", lambda values: values[values != ""].mode().iloc[0] if any(values != "") else ""),
    )
    metrics_df["error_rate"] = metrics_df["error_count"] / metrics_df["request_count"]
    metrics_df = metrics_df.sort_values(["service_name", "hour"]).reset_index(drop=True)
    metrics_df["deployment_changed"] = metrics_df.groupby("service_name")["deployment_version"].transform(lambda series: series.ne(series.shift(1)))

    validate_metrics(metrics_df, logs_df)
    quality_report = build_data_quality_report(logs_df, metrics_df)

    incident_windows = incidents_df.drop(columns=["affected_service_list"])
    logs_df.to_csv(target_dir / "structured_logs.csv", index=False)
    metrics_df.to_csv(target_dir / "service_hourly_metrics.csv", index=False)
    incident_windows.to_csv(target_dir / "incident_windows.csv", index=False)
    (REPORTS_DIR / "data_quality_report.md").write_text(quality_report, encoding="utf-8")
    return {
        "structured_logs": logs_df,
        "service_hourly_metrics": metrics_df,
        "incident_windows": incident_windows,
    }


def validate_metrics(metrics_df: pd.DataFrame, logs_df: pd.DataFrame) -> None:
    if metrics_df["error_rate"].max() <= 0:
        raise ValueError("error_rate is zero across all service-hour metrics")
    if not (metrics_df["p95_latency_ms"] > metrics_df["avg_latency_ms"]).any():
        raise ValueError("p95_latency_ms never exceeds avg_latency_ms")
    request_spread = metrics_df.groupby("service_name")["request_count"].agg(lambda series: float(series.max() - series.min()))
    if (request_spread <= 5).any():
        raise ValueError("request_count shows insufficient hourly variation")
    if set(metrics_df["service_name"].unique()) != set(logs_df["service_name"].unique()):
        raise ValueError("service coverage in metrics is incomplete")


def build_data_quality_report(logs_df: pd.DataFrame, metrics_df: pd.DataFrame) -> str:
    missing_values = logs_df.isna().sum()
    duplicate_requests = int(logs_df["request_id"].duplicated().sum())
    error_rates = logs_df.groupby("service_name")["is_error"].mean().sort_values(ascending=False)
    request_variance = metrics_df.groupby("service_name")["request_count"].agg(["min", "mean", "max"]).round(2)

    lines = [
        "# Data Quality Report",
        "",
        "Synthetic platform telemetry was normalized into service-level hourly metrics with incident flags.",
        "",
        "## Summary",
        f"- Raw log rows: {len(logs_df)}",
        f"- Hourly metric rows: {len(metrics_df)}",
        f"- Timestamp range: {logs_df['timestamp'].min()} to {logs_df['timestamp'].max()}",
        f"- Duplicate request IDs: {duplicate_requests}",
        "",
        "## Missing Values",
    ]
    for column, value in missing_values.items():
        lines.append(f"- {column}: {int(value)}")
    lines.extend(["", "## Error Rate By Service"])
    for service_name, rate in error_rates.items():
        lines.append(f"- {service_name}: {rate * 100:.2f}%")
    lines.extend(["", "## Request Count Variation"])
    for service_name, row in request_variance.iterrows():
        lines.append(f"- {service_name}: min={row['min']}, mean={row['mean']}, max={row['max']}")
    lines.extend(["", "## Incident Coverage"])
    flagged = metrics_df[metrics_df["known_incident_flag"]]
    lines.append(f"- Incident-flagged service-hour rows: {len(flagged)}")
    lines.append(f"- Distinct incident labels: {flagged['incident_label'].replace('', pd.NA).dropna().nunique()}")
    return "\n".join(lines) + "\n"


def main() -> None:
    outputs = ingest_logs()
    print(
        "Ingestion complete:",
        f"structured_logs={len(outputs['structured_logs'])}",
        f"service_hourly_metrics={len(outputs['service_hourly_metrics'])}",
        f"incident_windows={len(outputs['incident_windows'])}",
    )


if __name__ == "__main__":
    main()
