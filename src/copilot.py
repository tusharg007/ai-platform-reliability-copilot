"""Template-based incident intelligence copilot without paid API dependencies."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PREDICTIONS_DIR, REPORTS_DIR
from src.retrieval import search_documents


def answer_question(question: str | None = None, incident_id: str | None = None) -> dict[str, object]:
    incidents_path = PREDICTIONS_DIR / "incidents.csv"
    incidents_df = pd.read_csv(incidents_path) if incidents_path.exists() else pd.DataFrame()

    selected_incident = None
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
    evidence = []
    if selected_incident:
        evidence.append(selected_incident["evidence_summary"])
        evidence.append(f"Affected services: {selected_incident['affected_services']}. Severity: {selected_incident['severity']}.")
    evidence.extend([item["title"] for item in retrieved[:3]])

    similar_items = [f"{item['source_type']}: {item['title']}" for item in retrieved[:3]]
    next_steps = recommend_steps(likely_cause)
    summary = (
        f"The current signal points to {likely_cause}. "
        f"This is a production-oriented prototype using synthetic platform logs and simulated incidents."
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
