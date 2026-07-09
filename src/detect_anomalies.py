"""Detect reliability anomalies from hourly service metrics."""

from __future__ import annotations

from pathlib import Path
import uuid

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, ensure_project_dirs


FEATURE_COLUMNS = [
    "avg_latency_ms",
    "p95_latency_ms",
    "error_rate",
    "memory_usage",
    "cpu_usage",
    "db_latency_ms",
    "queue_lag",
]


def detect_anomalies(processed_dir: Path | None = None, predictions_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    ensure_project_dirs()
    source_dir = processed_dir or PROCESSED_DATA_DIR
    target_dir = predictions_dir or PREDICTIONS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    metrics_df = pd.read_csv(source_dir / "service_hourly_metrics.csv")
    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    metrics_df = metrics_df.sort_values(["service_name", "region", "hour"]).reset_index(drop=True)

    anomaly_scores = []
    alerts = []
    for (service_name, region), service_df in metrics_df.groupby(["service_name", "region"]):
        service_df = service_df.copy().sort_values("hour")
        features = service_df[FEATURE_COLUMNS].fillna(service_df[FEATURE_COLUMNS].median())
        contamination = min(0.12, max(0.03, 8 / max(len(service_df), 40)))
        model = IsolationForest(random_state=42, contamination=contamination)
        raw_predictions = model.fit_predict(features)
        scores = -model.score_samples(features)
        service_df["iso_flag"] = raw_predictions == -1
        service_df["anomaly_score"] = scores

        for metric in FEATURE_COLUMNS:
            rolling_mean = service_df[metric].rolling(window=12, min_periods=6).mean()
            rolling_std = service_df[metric].rolling(window=12, min_periods=6).std().replace(0, np.nan)
            z_score = ((service_df[metric] - rolling_mean) / rolling_std).fillna(0)
            service_df[f"{metric}_zscore"] = z_score

        for _, row in service_df.iterrows():
            anomaly_scores.append(
                {
                    "timestamp": row["hour"].isoformat(),
                    "service_name": service_name,
                    "region": region,
                    "deployment_version": row["deployment_version"],
                    "anomaly_score": round(float(row["anomaly_score"]), 6),
                    "is_isolation_forest_outlier": bool(row["iso_flag"]),
                }
            )

            reasons = []
            if row["iso_flag"]:
                reasons.append("isolation_forest_outlier")
            for metric in FEATURE_COLUMNS:
                zscore_value = float(row[f"{metric}_zscore"])
                if metric == "error_rate" and zscore_value >= 2.5:
                    reasons.append("error_rate_zscore")
                elif metric != "error_rate" and zscore_value >= 3.0:
                    reasons.append(f"{metric}_zscore")
            if row["error_rate"] >= 0.12:
                reasons.append("error_rate_threshold")
            if row["p95_latency_ms"] >= 450:
                reasons.append("latency_threshold")
            if row["memory_usage"] >= 85:
                reasons.append("memory_pressure")
            if row["cpu_usage"] >= 85:
                reasons.append("cpu_pressure")
            if row["db_latency_ms"] >= 160:
                reasons.append("database_latency")
            if row["queue_lag"] >= 30:
                reasons.append("queue_backlog")

            if not reasons:
                continue

            max_score = max(
                float(row["error_rate"]) * 2.2,
                float(row["p95_latency_ms"]) / 500,
                float(row["memory_usage"]) / 100,
                float(row["cpu_usage"]) / 100,
                float(row["db_latency_ms"]) / 180,
                float(row["queue_lag"]) / 40,
                float(row["anomaly_score"]) / max(scores.max(), 0.0001),
            )
            severity = "critical" if max_score >= 1.5 else "high" if max_score >= 1.0 else "medium"
            alert_type = classify_alert_type(reasons)
            alerts.append(
                {
                    "alert_id": f"ALT-{uuid.uuid4().hex[:10]}",
                    "timestamp": row["hour"].isoformat(),
                    "service_name": service_name,
                    "region": region,
                    "severity": severity,
                    "anomaly_score": round(float(row["anomaly_score"]), 6),
                    "alert_type": alert_type,
                    "anomaly_reason": ", ".join(sorted(set(reasons))),
                    "suggested_investigation_area": suggested_investigation_area(alert_type),
                    "deployment_version": row["deployment_version"],
                }
            )

    anomaly_scores_df = pd.DataFrame(anomaly_scores).sort_values(["timestamp", "service_name"]).reset_index(drop=True)
    alerts_df = pd.DataFrame(alerts).sort_values(["timestamp", "severity"]).reset_index(drop=True)
    anomaly_scores_df.to_csv(target_dir / "anomaly_scores.csv", index=False)
    alerts_df.to_csv(target_dir / "reliability_alerts.csv", index=False)
    return {"anomaly_scores": anomaly_scores_df, "reliability_alerts": alerts_df}


def classify_alert_type(reasons: list[str]) -> str:
    joined = " ".join(reasons)
    if "database" in joined:
        return "database_latency"
    if "memory" in joined:
        return "memory_pressure"
    if "queue" in joined:
        return "queue_backlog"
    if "cpu" in joined or "latency" in joined:
        return "latency_regression"
    if "error_rate" in joined:
        return "error_spike"
    return "generic_anomaly"


def suggested_investigation_area(alert_type: str) -> str:
    mapping = {
        "database_latency": "Inspect slow queries, connection pool saturation, and downstream timeout propagation.",
        "memory_pressure": "Review heap growth, memory retention patterns, and restart behavior.",
        "queue_backlog": "Check worker throughput, queue consumer lag, and retry storm conditions.",
        "latency_regression": "Compare recent deployments, CPU saturation, and upstream dependency latency.",
        "error_spike": "Investigate application exceptions, recent config changes, and dependency availability.",
        "generic_anomaly": "Start with correlated logs, recent releases, and service dependency health.",
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
