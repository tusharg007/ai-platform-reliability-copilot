"""Detect varied reliability anomalies from service-hour metrics."""

from __future__ import annotations

from pathlib import Path
import uuid

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, ensure_project_dirs


FEATURE_COLUMNS = [
    "error_rate",
    "p95_latency_ms",
    "avg_memory_usage",
    "avg_cpu_usage",
    "avg_db_latency_ms",
    "avg_queue_lag",
    "auth_failure_rate",
    "status_5xx_rate",
]

METRIC_TO_ALERT = {
    "p95_latency_ms": "latency_spike",
    "error_rate": "error_rate_spike",
    "avg_memory_usage": "memory_pressure",
    "avg_cpu_usage": "cpu_pressure",
    "avg_db_latency_ms": "db_latency_spike",
    "avg_queue_lag": "queue_backlog",
    "auth_failure_rate": "auth_failure_spike",
    "status_5xx_rate": "external_api_failure",
}


def detect_anomalies(processed_dir: Path | None = None, predictions_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    ensure_project_dirs()
    source_dir = processed_dir or PROCESSED_DATA_DIR
    target_dir = predictions_dir or PREDICTIONS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    metrics_df = pd.read_csv(source_dir / "service_hourly_metrics.csv")
    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    metrics_df = metrics_df.sort_values(["service_name", "hour"]).reset_index(drop=True)

    anomaly_rows: list[dict[str, object]] = []
    alert_rows: list[dict[str, object]] = []

    for service_name, service_df in metrics_df.groupby("service_name"):
        service_df = service_df.copy().sort_values("hour").reset_index(drop=True)
        features = service_df[FEATURE_COLUMNS].fillna(service_df[FEATURE_COLUMNS].median())
        model = IsolationForest(random_state=42, contamination=0.06)
        model.fit(features)
        iso_score = -model.score_samples(features)
        iso_flag = model.predict(features) == -1
        service_df["iso_score"] = iso_score
        service_df["iso_flag"] = iso_flag

        rolling_stats = {}
        for metric in FEATURE_COLUMNS:
            rolling_median = service_df[metric].rolling(window=24, min_periods=8).median()
            rolling_mad = service_df[metric].rolling(window=24, min_periods=8).apply(_mad, raw=False).replace(0, np.nan)
            robust_z = ((service_df[metric] - rolling_median) / (1.4826 * rolling_mad)).fillna(0.0)
            rolling_mean = service_df[metric].rolling(window=24, min_periods=8).mean()
            rolling_stats[metric] = (rolling_mean.fillna(service_df[metric].expanding().mean()), robust_z)
            service_df[f"{metric}_baseline"] = rolling_mean.fillna(service_df[metric].expanding().mean())
            service_df[f"{metric}_robust_z"] = robust_z

        for idx, row in service_df.iterrows():
            max_z = float(max(abs(row[f"{metric}_robust_z"]) for metric in FEATURE_COLUMNS))
            anomaly_rows.append(
                {
                    "timestamp": row["hour"].isoformat(),
                    "service_name": service_name,
                    "anomaly_score": round(float(row["iso_score"]), 6),
                    "is_isolation_forest_outlier": bool(row["iso_flag"]),
                    "max_robust_zscore": round(max_z, 4),
                    "known_incident_flag": bool(row["known_incident_flag"]),
                    "deployment_version": row["deployment_version"],
                }
            )

            for metric in FEATURE_COLUMNS:
                metric_value = float(row[metric])
                baseline_value = float(row[f"{metric}_baseline"])
                robust_z = float(row[f"{metric}_robust_z"])
                if not is_metric_alert(metric, metric_value, baseline_value, robust_z, row):
                    continue

                alert_type = infer_alert_type(metric, row, service_df, idx)
                severity = infer_severity(metric, metric_value, baseline_value, robust_z, float(row["iso_score"]))
                alert_rows.append(
                    {
                        "alert_id": f"ALT-{uuid.uuid4().hex[:10]}",
                        "timestamp": row["hour"].isoformat(),
                        "service_name": service_name,
                        "severity": severity,
                        "alert_type": alert_type,
                        "anomaly_score": round(float(row["iso_score"]), 6),
                        "metric_name": metric,
                        "metric_value": round(metric_value, 6),
                        "baseline_value": round(baseline_value, 6),
                        "anomaly_reason": build_reason(metric, metric_value, baseline_value, robust_z, row),
                        "suggested_investigation_area": suggested_investigation_area(alert_type),
                        "deployment_version": row["deployment_version"],
                    }
                )

    anomaly_scores_df = pd.DataFrame(anomaly_rows).sort_values(["timestamp", "service_name"]).reset_index(drop=True)
    alerts_df = (
        pd.DataFrame(alert_rows)
        .sort_values(["timestamp", "severity", "service_name"], ascending=[True, False, True])
        .reset_index(drop=True)
    )
    if alerts_df.empty:
        raise ValueError("Anomaly detection produced no alerts")

    anomaly_scores_df.to_csv(target_dir / "anomaly_scores.csv", index=False)
    alerts_df.to_csv(target_dir / "reliability_alerts.csv", index=False)
    return {"anomaly_scores": anomaly_scores_df, "reliability_alerts": alerts_df}


def _mad(series: pd.Series) -> float:
    median = series.median()
    return float((series - median).abs().median())


def is_metric_alert(metric: str, metric_value: float, baseline_value: float, robust_z: float, row: pd.Series) -> bool:
    if metric in {"error_rate", "status_5xx_rate"}:
        return metric_value > max(0.015, baseline_value * 1.8) and robust_z >= 1.4
    if metric == "auth_failure_rate":
        return metric_value > max(0.03, baseline_value * 2.2) and robust_z >= 1.2
    if metric == "avg_queue_lag":
        return metric_value > max(10, baseline_value * 1.8) and robust_z >= 1.2
    if metric == "avg_db_latency_ms":
        return metric_value > max(35, baseline_value * 1.9) and robust_z >= 1.4
    if metric == "avg_memory_usage":
        return metric_value > max(72, baseline_value * 1.18) and robust_z >= 1.2
    if metric == "avg_cpu_usage":
        return metric_value > max(70, baseline_value * 1.18) and robust_z >= 1.2
    if metric == "p95_latency_ms":
        return metric_value > max(140, baseline_value * 1.35) and robust_z >= 1.3
    return False


def infer_alert_type(metric: str, row: pd.Series, service_df: pd.DataFrame, idx: int) -> str:
    if bool(row["deployment_changed"]) and metric in {"error_rate", "p95_latency_ms", "status_5xx_rate"}:
        return "deployment_regression"
    if metric == "auth_failure_rate":
        return "auth_failure_spike"
    if metric == "avg_queue_lag":
        return "queue_backlog"
    if metric == "avg_db_latency_ms":
        return "db_latency_spike"
    if metric == "avg_memory_usage":
        return "memory_pressure"
    if metric == "avg_cpu_usage":
        return "cpu_pressure"
    if metric == "p95_latency_ms":
        return "latency_spike"
    if metric == "status_5xx_rate" and row["service_name"] in {"payment-service", "notification-service"}:
        return "external_api_failure"
    return METRIC_TO_ALERT[metric]


def infer_severity(metric: str, metric_value: float, baseline_value: float, robust_z: float, iso_score: float) -> str:
    ratio = metric_value / max(baseline_value, 1e-6)
    score = max(abs(robust_z), ratio, iso_score / 0.55)
    if metric in {"avg_queue_lag", "avg_db_latency_ms"}:
        score += 0.2
    if metric == "auth_failure_rate":
        score += 0.1
    if score >= 4.2:
        return "critical"
    if score >= 3.0:
        return "high"
    if score >= 2.0:
        return "medium"
    return "low"


def build_reason(metric: str, metric_value: float, baseline_value: float, robust_z: float, row: pd.Series) -> str:
    fragments = [
        f"{metric}={metric_value:.4f}",
        f"baseline={baseline_value:.4f}",
        f"robust_z={robust_z:.2f}",
    ]
    if bool(row["deployment_changed"]):
        fragments.append("deployment changed in this hour")
    if bool(row["known_incident_flag"]):
        fragments.append("overlaps synthetic known incident window")
    if bool(row["iso_flag"]):
        fragments.append("Isolation Forest also flagged this row")
    return "; ".join(fragments)


def suggested_investigation_area(alert_type: str) -> str:
    mapping = {
        "latency_spike": "Compare recent releases, top slow endpoints, and upstream dependency latency.",
        "error_rate_spike": "Inspect exceptions, dependency failures, and user-impacting error slices.",
        "memory_pressure": "Review heap growth, cache retention, and restart behavior.",
        "cpu_pressure": "Inspect expensive code paths, batch fan-out, and autoscaling sufficiency.",
        "db_latency_spike": "Check slow queries, connection pool saturation, and lock contention.",
        "queue_backlog": "Measure consumer throughput, retries, and dead-letter activity.",
        "deployment_regression": "Diff the rollout against the previous version and validate rollback criteria.",
        "auth_failure_spike": "Inspect token validation, session expiry, and identity-provider dependencies.",
        "external_api_failure": "Check third-party provider availability and fallback behavior.",
    }
    return mapping[alert_type]


def main() -> None:
    outputs = detect_anomalies()
    print(
        "Anomaly detection complete:",
        f"scores={len(outputs['anomaly_scores'])}",
        f"alerts={len(outputs['reliability_alerts'])}",
    )


if __name__ == "__main__":
    main()
