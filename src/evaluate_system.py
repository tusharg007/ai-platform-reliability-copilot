"""Evaluate synthetic anomaly detection, clustering, retrieval, and risk scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, REPORTS_DIR, ensure_project_dirs
from src.retrieval import search_documents


def evaluate_system(
    raw_dir: Path | None = None,
    processed_dir: Path | None = None,
    predictions_dir: Path | None = None,
) -> dict[str, object]:
    ensure_project_dirs()
    raw_root = raw_dir or RAW_DATA_DIR
    processed_root = processed_dir or PROCESSED_DATA_DIR
    prediction_root = predictions_dir or PREDICTIONS_DIR

    known_df = pd.read_csv(raw_root / "known_incidents.csv")
    metrics_df = pd.read_csv(processed_root / "service_hourly_metrics.csv")
    alerts_df = pd.read_csv(prediction_root / "reliability_alerts.csv")
    incidents_df = pd.read_csv(prediction_root / "incidents.csv")
    risk_df = pd.read_csv(prediction_root / "service_risk_scores.csv")

    known_df["start_time"] = pd.to_datetime(known_df["start_time"], utc=True)
    known_df["end_time"] = pd.to_datetime(known_df["end_time"], utc=True)
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)
    incidents_df["end_time"] = pd.to_datetime(incidents_df["end_time"], utc=True)

    matched_incidents = 0
    alert_matches = []
    for incident in known_df.to_dict(orient="records"):
        affected = str(incident["affected_services"]).split(",")
        overlap = alerts_df[
            alerts_df["service_name"].isin(affected)
            & (alerts_df["timestamp"] >= incident["start_time"])
            & (alerts_df["timestamp"] <= incident["end_time"])
        ]
        if not overlap.empty:
            matched_incidents += 1
        alert_matches.append(len(overlap))

    detection_recall = matched_incidents / len(known_df) if len(known_df) else 0.0
    precision_estimate = (
        len(alerts_df[alerts_df.apply(lambda row: alert_in_known_window(row, known_df), axis=1)]) / len(alerts_df)
        if len(alerts_df)
        else 0.0
    )

    clustered_matches = 0
    for incident in known_df.to_dict(orient="records"):
        affected = str(incident["affected_services"]).split(",")
        overlap = incidents_df[
            incidents_df["affected_services"].apply(lambda text: any(service in str(text) for service in affected))
            & (incidents_df["start_time"] <= incident["end_time"])
            & (incidents_df["end_time"] >= incident["start_time"])
        ]
        if not overlap.empty:
            clustered_matches += 1
    clustering_overlap = clustered_matches / len(known_df) if len(known_df) else 0.0

    retrieval_queries = [
        ("database timeout causing upstream 504s", "database_timeout"),
        ("invalid session and token failures", "authentication_failure"),
        ("worker lag and notification delays", "queue_backlog"),
        ("provider 502 errors on payment flow", "external"),
    ]
    retrieval_hits = 0
    for query, expected_term in retrieval_queries:
        results = search_documents(query, top_k=3)
        joined = " ".join(item["title"] + " " + item["content"] for item in results).lower()
        if expected_term.replace("_", " ") in joined or expected_term in joined:
            retrieval_hits += 1
    retrieval_relevance = retrieval_hits / len(retrieval_queries) if retrieval_queries else 0.0

    risk_score_span = float(risk_df["risk_score"].max() - risk_df["risk_score"].min()) if not risk_df.empty else 0.0
    risk_band_count = int(risk_df["risk_band"].nunique()) if not risk_df.empty else 0
    top_risk_service = str(risk_df.sort_values("risk_score", ascending=False).iloc[0]["service_name"]) if not risk_df.empty else "n/a"

    metrics = {
        "incident_detection_recall": round(detection_recall, 4),
        "alert_precision_estimate": round(precision_estimate, 4),
        "incident_clustering_overlap": round(clustering_overlap, 4),
        "retrieval_relevance_at_3": round(retrieval_relevance, 4),
        "risk_score_span": round(risk_score_span, 2),
        "risk_band_count": risk_band_count,
        "top_risk_service": top_risk_service,
        "evaluation_note": "Metrics are approximate because alerts and incidents are compared against synthetic ground truth.",
    }
    write_reports(metrics, known_df, metrics_df, alerts_df, incidents_df, risk_df)
    return metrics


def alert_in_known_window(row: pd.Series, known_df: pd.DataFrame) -> bool:
    service_name = str(row["service_name"])
    timestamp = pd.Timestamp(row["timestamp"])
    overlap = known_df[
        known_df["affected_services"].str.contains(service_name)
        & (known_df["start_time"] <= timestamp)
        & (known_df["end_time"] >= timestamp)
    ]
    return not overlap.empty


def write_reports(
    metrics: dict[str, object],
    known_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    alerts_df: pd.DataFrame,
    incidents_df: pd.DataFrame,
    risk_df: pd.DataFrame,
) -> None:
    model_lines = [
        "# Model Evaluation",
        "",
        "The following results are based on synthetic ground truth and simulated incidents. They are useful for sanity checking, not for claiming production accuracy.",
        "",
    ]
    for key, value in metrics.items():
        model_lines.append(f"- {key}: {value}")
    (REPORTS_DIR / "model_evaluation.md").write_text("\n".join(model_lines) + "\n", encoding="utf-8")

    incident_lines = [
        "# Incident Analysis Report",
        "",
        f"- Known incidents: {len(known_df)}",
        f"- Reliability alerts: {len(alerts_df)}",
        f"- Clustered incidents: {len(incidents_df)}",
        f"- High-risk services: {int(risk_df['risk_band'].isin(['High', 'Critical']).sum())}",
        "",
        "## Top Risk Services",
    ]
    for row in risk_df.head(5).to_dict(orient="records"):
        incident_lines.append(
            f"- {row['service_name']}: score={row['risk_score']}, band={row['risk_band']}, drivers={row['top_risk_driver_1']}, {row['top_risk_driver_2']}"
        )
    (REPORTS_DIR / "incident_analysis_report.md").write_text("\n".join(incident_lines) + "\n", encoding="utf-8")

    root_lines = [
        "# Root Cause Analysis",
        "",
        "The calibrated synthetic scenarios generate distinct patterns such as deployment regressions, queue backlog, database timeout propagation, external provider failures, and auth spikes.",
        "",
        "## Incident Samples",
    ]
    for row in incidents_df.head(8).to_dict(orient="records"):
        root_lines.append(
            f"- {row['incident_id']}: {row['primary_service']} | {row['suspected_root_cause']} | {row['severity']} | alerts={row['alert_count']}"
        )
    (REPORTS_DIR / "root_cause_analysis.md").write_text("\n".join(root_lines) + "\n", encoding="utf-8")
    (REPORTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def main() -> None:
    metrics = evaluate_system()
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
