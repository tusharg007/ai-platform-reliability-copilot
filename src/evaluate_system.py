"""Evaluate anomaly detection, clustering, retrieval, and service risk scoring."""

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
) -> dict[str, float]:
    ensure_project_dirs()
    raw = raw_dir or RAW_DATA_DIR
    processed = processed_dir or PROCESSED_DATA_DIR
    predictions = predictions_dir or PREDICTIONS_DIR

    known_df = pd.read_csv(raw / "known_incidents.csv")
    alerts_df = pd.read_csv(predictions / "reliability_alerts.csv")
    incidents_df = pd.read_csv(predictions / "incidents.csv")
    risk_df = pd.read_csv(predictions / "service_risk_scores.csv")
    metrics_df = pd.read_csv(processed / "service_hourly_metrics.csv")

    known_df["start_time"] = pd.to_datetime(known_df["start_time"], utc=True)
    known_df["end_time"] = pd.to_datetime(known_df["end_time"], utc=True)
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)
    incidents_df["end_time"] = pd.to_datetime(incidents_df["end_time"], utc=True)

    detected_known = 0
    for row in known_df.to_dict(orient="records"):
        overlap = alerts_df[
            (alerts_df["service_name"].isin(str(row["affected_services"]).split(",")))
            & (alerts_df["timestamp"] >= row["start_time"])
            & (alerts_df["timestamp"] <= row["end_time"])
        ]
        if not overlap.empty:
            detected_known += 1
    anomaly_recall = detected_known / len(known_df) if len(known_df) else 0.0

    clustered_known = 0
    for row in known_df.to_dict(orient="records"):
        overlap = incidents_df[
            (incidents_df["primary_service"] == row["primary_service"])
            & (incidents_df["start_time"] <= row["end_time"])
            & (incidents_df["end_time"] >= row["start_time"])
        ]
        if not overlap.empty:
            clustered_known += 1
    clustering_overlap = clustered_known / len(known_df) if len(known_df) else 0.0

    labeled_queries = [
        ("database timeout after deployment", "database_timeout"),
        ("memory keeps rising on recommendation service", "memory_leak"),
        ("worker lag and queue growth", "queue_backlog"),
    ]
    retrieval_hits = 0
    for query, expected in labeled_queries:
        results = search_documents(query, top_k=3)
        joined_titles = " ".join(item["title"] for item in results).lower()
        if expected.replace("_", " ") in joined_titles or expected in joined_titles:
            retrieval_hits += 1
    retrieval_relevance = retrieval_hits / len(labeled_queries) if labeled_queries else 0.0

    top_risk_service = str(risk_df.sort_values("risk_score", ascending=False).iloc[0]["service_name"]) if not risk_df.empty else "n/a"
    recent_peak_latency = float(metrics_df["p95_latency_ms"].max()) if not metrics_df.empty else 0.0
    risk_sanity = 1.0 if top_risk_service in {"database-service", "api-gateway", "payment-service", "worker-service"} else 0.0

    metrics = {
        "anomaly_incident_recall": round(anomaly_recall, 4),
        "incident_clustering_overlap": round(clustering_overlap, 4),
        "retrieval_relevance_at_3": round(retrieval_relevance, 4),
        "risk_scoring_sanity": round(risk_sanity, 4),
        "top_risk_service": top_risk_service,
        "recent_peak_p95_latency_ms": round(recent_peak_latency, 2),
    }

    write_reports(metrics, known_df, incidents_df, risk_df)
    return metrics


def write_reports(metrics: dict[str, float], known_df: pd.DataFrame, incidents_df: pd.DataFrame, risk_df: pd.DataFrame) -> None:
    model_eval = [
        "# Model Evaluation",
        "",
        "These metrics are approximate because the system is evaluated against synthetic ground truth and simulated incidents.",
        "",
    ]
    for key, value in metrics.items():
        model_eval.append(f"- {key}: {value}")
    (REPORTS_DIR / "model_evaluation.md").write_text("\n".join(model_eval) + "\n", encoding="utf-8")

    incident_report = [
        "# Incident Analysis Report",
        "",
        "Clustered incidents are compared against synthetic known incidents for overlap-based evaluation.",
        "",
        f"- Known incidents: {len(known_df)}",
        f"- Predicted clustered incidents: {len(incidents_df)}",
        f"- Top risk service: {metrics['top_risk_service']}",
        "",
        "## High-Risk Services",
    ]
    for row in risk_df.head(5).to_dict(orient="records"):
        incident_report.append(f"- {row['service_name']}: {row['risk_score']} ({row['risk_band']})")
    (REPORTS_DIR / "incident_analysis_report.md").write_text("\n".join(incident_report) + "\n", encoding="utf-8")

    root_cause = [
        "# Root Cause Analysis",
        "",
        "Synthetic incidents map to patterns such as deployment regressions, queue backlog, database timeout propagation, and memory pressure.",
        "",
    ]
    if not incidents_df.empty:
        for row in incidents_df.head(6).to_dict(orient="records"):
            root_cause.append(f"- {row['incident_id']}: {row['primary_service']} -> {row['suspected_root_cause']}")
    (REPORTS_DIR / "root_cause_analysis.md").write_text("\n".join(root_cause) + "\n", encoding="utf-8")
    (REPORTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def main() -> None:
    metrics = evaluate_system()
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
