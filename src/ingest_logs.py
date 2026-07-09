"""Normalize raw logs and build service-hourly analytics tables."""

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

    logs_path = source_dir / "platform_logs.csv"
    incidents_path = source_dir / "known_incidents.csv"

    logs_df = pd.read_csv(logs_path)
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(logs_df.columns))
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    logs_df["timestamp"] = pd.to_datetime(logs_df["timestamp"], utc=True)
    logs_df["error_type"] = logs_df["error_type"].fillna("")
    logs_df["message"] = logs_df["message"].fillna("")
    logs_df["endpoint"] = logs_df["endpoint"].fillna("unknown")
    logs_df["log_level"] = logs_df["log_level"].fillna("INFO")
    logs_df = logs_df.sort_values("timestamp").reset_index(drop=True)

    logs_df["hour"] = logs_df["timestamp"].dt.floor("h")
    logs_df["is_error"] = logs_df["status_code"] >= 500
    logs_df["is_auth_failure"] = logs_df["status_code"].isin([401, 403])
    logs_df["is_timeout"] = logs_df["error_type"].str.contains("TIMEOUT", case=False, na=False)

    grouped = logs_df.groupby(["hour", "service_name", "region", "deployment_version"], as_index=False)
    metrics_df = grouped.agg(
        request_count=("request_id", "count"),
        error_count=("is_error", "sum"),
        auth_failure_count=("is_auth_failure", "sum"),
        timeout_count=("is_timeout", "sum"),
        avg_latency_ms=("latency_ms", "mean"),
        p95_latency_ms=("latency_ms", lambda series: series.quantile(0.95)),
        cpu_usage=("cpu_usage", "mean"),
        memory_usage=("memory_usage", "mean"),
        db_latency_ms=("db_latency_ms", "mean"),
        queue_lag=("queue_lag", "mean"),
    )
    metrics_df["error_rate"] = metrics_df["error_count"] / metrics_df["request_count"]
    metrics_df["auth_failure_rate"] = metrics_df["auth_failure_count"] / metrics_df["request_count"]

    incidents_df = pd.read_csv(incidents_path)
    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)
    incidents_df["end_time"] = pd.to_datetime(incidents_df["end_time"], utc=True)
    incident_windows = incidents_df.rename(columns={"incident_type": "suspected_root_cause"}).copy()

    quality_report = build_data_quality_report(logs_df, metrics_df)

    logs_df.to_csv(target_dir / "structured_logs.csv", index=False)
    metrics_df.to_csv(target_dir / "service_hourly_metrics.csv", index=False)
    incident_windows.to_csv(target_dir / "incident_windows.csv", index=False)
    (REPORTS_DIR / "data_quality_report.md").write_text(quality_report, encoding="utf-8")

    return {
        "structured_logs": logs_df,
        "service_hourly_metrics": metrics_df,
        "incident_windows": incident_windows,
    }


def build_data_quality_report(logs_df: pd.DataFrame, metrics_df: pd.DataFrame) -> str:
    missing_values = logs_df.isna().sum().sort_values(ascending=False)
    duplicate_requests = int(logs_df["request_id"].duplicated().sum())
    log_level_distribution = logs_df["log_level"].value_counts(normalize=True).round(4)
    service_coverage = logs_df["service_name"].value_counts().sort_index()
    timestamp_min = logs_df["timestamp"].min()
    timestamp_max = logs_df["timestamp"].max()
    error_rates = (
        logs_df.groupby("service_name")["is_error"].mean().sort_values(ascending=False).round(4)
    )

    lines = [
        "# Data Quality Report",
        "",
        "This report reflects generated synthetic platform telemetry after ingestion and normalization.",
        "",
        "## Summary",
        f"- Records analyzed: {len(logs_df)}",
        f"- Hourly metric rows: {len(metrics_df)}",
        f"- Timestamp range: {timestamp_min} to {timestamp_max}",
        f"- Duplicate request IDs: {duplicate_requests}",
        "",
        "## Missing Values",
    ]
    for column, count in missing_values.items():
        lines.append(f"- {column}: {int(count)}")
    lines.extend(["", "## Log Level Distribution"])
    for level, share in log_level_distribution.items():
        lines.append(f"- {level}: {share * 100:.2f}%")
    lines.extend(["", "## Service Coverage"])
    for service, count in service_coverage.items():
        lines.append(f"- {service}: {int(count)} rows")
    lines.extend(["", "## Error Rate By Service"])
    for service, rate in error_rates.items():
        lines.append(f"- {service}: {rate * 100:.2f}%")
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
