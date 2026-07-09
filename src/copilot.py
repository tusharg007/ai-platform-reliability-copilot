"""Template-based incident intelligence copilot without paid API dependencies."""

from __future__ import annotations

import pandas as pd

from src.config import PREDICTIONS_DIR, REPORTS_DIR
from src.retrieval import search_documents


def answer_question(question: str | None = None, incident_id: str | None = None) -> dict[str, object]:
    incidents_path = PREDICTIONS_DIR / "incidents.csv"
    risk_path = PREDICTIONS_DIR / "service_risk_scores.csv"
    alerts_path = PREDICTIONS_DIR / "reliability_alerts.csv"
    incidents_df = pd.read_csv(incidents_path) if incidents_path.exists() else pd.DataFrame()
    risk_df = pd.read_csv(risk_path) if risk_path.exists() else pd.DataFrame()
    alerts_df = pd.read_csv(alerts_path) if alerts_path.exists() else pd.DataFrame()
    if not alerts_df.empty:
        alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)

    selected_incident = None
    inferred_service = infer_service_from_question(question, incident_id, incidents_df, risk_df)
    if incident_id and not incidents_df.empty:
        match = incidents_df[incidents_df["incident_id"] == incident_id]
        if not match.empty:
            selected_incident = match.iloc[0].to_dict()
            query = f"{incident_id} {selected_incident['suspected_root_cause']} {selected_incident['evidence_summary']}"
        else:
            query = question or incident_id
    else:
        query = question or "Summarize the latest platform reliability incident."

    retrieved = search_documents(query, top_k=4)
    likely_cause = selected_incident["suspected_root_cause"] if selected_incident else infer_likely_cause(retrieved)
    evidence: list[str] = []
    related_incidents: list[str] = []
    top_drivers: list[str] = []
    risk_score = None
    risk_band = None
    error_rate = None
    p95_latency = None
    high_alert_count = None
    recent_alert_types: list[str] = []

    if inferred_service and not risk_df.empty:
        service_risk = risk_df[risk_df["service_name"] == inferred_service]
        if not service_risk.empty:
            risk_row = service_risk.iloc[0]
            risk_score = float(risk_row["risk_score"])
            risk_band = str(risk_row["risk_band"])
            error_rate = float(risk_row["error_rate"])
            p95_latency = float(risk_row["p95_latency_ms"])
            high_alert_count = int(risk_row["high_critical_alert_count"])
            top_drivers = [str(risk_row["top_risk_driver_1"]), str(risk_row["top_risk_driver_2"]), str(risk_row["top_risk_driver_3"])]
            evidence.extend(
                [
                    f"Risk score: {risk_score:.2f}",
                    f"Risk band: {risk_band}",
                    f"24h error rate: {error_rate * 100:.2f}%",
                    f"P95 latency: {p95_latency:.1f} ms",
                    f"Recent high/critical alert count: {high_alert_count}",
                    f"Top risk drivers: {', '.join(top_drivers)}",
                ]
            )
    if inferred_service and not incidents_df.empty:
        service_incidents = incidents_df[
            incidents_df["primary_service"].eq(inferred_service)
            | incidents_df["affected_services"].str.contains(inferred_service, na=False)
        ].sort_values("start_time", ascending=False).head(3)
        related_incidents = service_incidents["incident_id"].tolist()
        if related_incidents:
            evidence.append(f"Related incidents: {', '.join(related_incidents)}")
    if inferred_service and not alerts_df.empty:
        service_alerts = alerts_df[alerts_df["service_name"] == inferred_service].sort_values("timestamp", ascending=False).head(15)
        recent_alert_types = service_alerts["alert_type"].dropna().unique().tolist()[:4]
        if recent_alert_types:
            evidence.append(f"Recent alert types: {', '.join(recent_alert_types)}")

    if selected_incident:
        evidence.append(selected_incident["evidence_summary"])
        evidence.append(f"Affected services: {selected_incident['affected_services']}. Severity: {selected_incident['severity']}.")
    evidence.extend([item["title"] for item in retrieved[:3]])

    similar_items = [f"{item['source_type']}: {item['title']}" for item in retrieved[:3]]
    next_steps = recommend_steps(likely_cause)
    if inferred_service and risk_score is not None and risk_band is not None:
        summary = (
            f"{inferred_service} is currently classified as {risk_band} risk with a score of {risk_score:.2f}. "
            f"Recent windows show elevated reliability pressure consistent with {likely_cause}. "
            "This is a production-oriented prototype using synthetic platform logs and simulated incidents."
        )
    else:
        summary = (
            f"The current signal points to {likely_cause}. "
            "This is a production-oriented prototype using synthetic platform logs and simulated incidents."
        )
    response = {
        "Summary": summary,
        "Likely cause": likely_cause,
        "Supporting evidence": evidence,
        "Similar incidents/runbooks": similar_items,
        "Recommended next debugging steps": next_steps,
        "Human review note": "Validate the hypothesis against live traces, deployment notes, and on-call context before acting.",
    }
    return response


def infer_service_from_question(
    question: str | None,
    incident_id: str | None,
    incidents_df: pd.DataFrame,
    risk_df: pd.DataFrame,
) -> str | None:
    candidates = risk_df["service_name"].tolist() if not risk_df.empty else []
    text = f"{question or ''} {incident_id or ''}".lower()
    for service_name in candidates:
        if service_name in text:
            return service_name
    if incident_id and not incidents_df.empty:
        match = incidents_df[incidents_df["incident_id"] == incident_id]
        if not match.empty:
            return str(match.iloc[0]["primary_service"])
    return "payment-service" if "payment-service" in candidates else (candidates[0] if candidates else None)


def infer_likely_cause(retrieved: list[dict[str, object]]) -> str:
    if not retrieved:
        return "insufficient context"
    title = str(retrieved[0]["title"]).lower()
    if "database" in title:
        return "database timeout or downstream query latency"
    if "memory" in title:
        return "memory leak or sustained memory pressure"
    if "deployment" in title:
        return "deployment regression after a recent release"
    if "queue" in title:
        return "queue backlog and worker lag"
    if "auth" in title:
        return "authentication failure spike"
    return "multi-signal service degradation requiring human triage"


def recommend_steps(cause: str) -> list[str]:
    cause_lower = cause.lower()
    if "database" in cause_lower:
        return [
            "Inspect slow queries, connection pool saturation, and timeout budgets.",
            "Compare affected deployment versions and rollback criteria.",
            "Trace which upstream services inherit the timeout behavior.",
        ]
    if "memory" in cause_lower:
        return [
            "Review memory growth by deployment version and restart frequency.",
            "Inspect caches, long-lived objects, and batch processing behavior.",
            "Load-test the suspected code path with heap monitoring enabled.",
        ]
    if "deployment" in cause_lower:
        return [
            "Diff config and code changes introduced in the latest release.",
            "Rollback or disable the change behind a feature flag if possible.",
            "Check whether the regression is region-specific or global.",
        ]
    return [
        "Correlate anomalies with recent releases, traffic shifts, and dependency health.",
        "Inspect high-severity logs and representative traces from the incident window.",
        "Have an engineer verify the recommendation before mitigation.",
    ]


def render_sample_outputs() -> str:
    examples = [
        ("Why did database-service trigger upstream timeouts?", answer_question("Why did database-service trigger upstream timeouts?")),
        ("Summarize INC-CLUSTER-001", answer_question(incident_id="INC-CLUSTER-001")),
    ]
    lines = [
        "# Sample Copilot Responses",
        "",
        "These examples are generated from synthetic telemetry and retrieved runbooks.",
        "",
    ]
    for prompt, response in examples:
        lines.append(f"## Prompt: {prompt}")
        lines.append("")
        for key, value in response.items():
            lines.append(f"### {key}")
            if isinstance(value, list):
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append(str(value))
            lines.append("")
    content = "\n".join(lines)
    (REPORTS_DIR / "sample_copilot_responses.md").write_text(content, encoding="utf-8")
    return content


def main() -> None:
    print(render_sample_outputs())


if __name__ == "__main__":
    main()
