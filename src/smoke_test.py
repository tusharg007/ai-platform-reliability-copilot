"""Run a lightweight data and API smoke test without visualization dependencies."""

from __future__ import annotations

import pandas as pd

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR
from src.copilot import answer_question, render_sample_outputs
from src.validate_outputs import validate_outputs


def main() -> None:
    metrics_path = PROCESSED_DATA_DIR / "service_hourly_metrics.csv"
    alerts_path = PREDICTIONS_DIR / "reliability_alerts.csv"
    incidents_path = PREDICTIONS_DIR / "incidents.csv"
    risks_path = PREDICTIONS_DIR / "service_risk_scores.csv"

    for path in [metrics_path, alerts_path, incidents_path, risks_path]:
        if not path.exists():
            raise FileNotFoundError(f"Required smoke-test artifact missing: {path.name}")

    metrics_df = pd.read_csv(metrics_path)
    alerts_df = pd.read_csv(alerts_path)
    incidents_df = pd.read_csv(incidents_path)
    risk_df = pd.read_csv(risks_path)

    assert not metrics_df.empty
    assert not alerts_df.empty
    assert not incidents_df.empty
    assert not risk_df.empty
    assert {"service_name", "error_rate", "p95_latency_ms"}.issubset(metrics_df.columns)
    assert {"alert_id", "alert_type", "severity"}.issubset(alerts_df.columns)
    assert {"incident_id", "primary_service", "severity"}.issubset(incidents_df.columns)
    assert {"service_name", "risk_score", "risk_band"}.issubset(risk_df.columns)
    assert risk_df["risk_score"].nunique() > 1
    assert float(risk_df["risk_score"].max() - risk_df["risk_score"].min()) >= 20
    assert risk_df["risk_band"].nunique() >= 3

    render_sample_outputs()
    assert (REPORTS_DIR / "sample_copilot_responses.md").exists()

    validate_outputs()
    response = answer_question("Why did the database timeout propagate to upstream services?")
    assert response["Likely cause"]
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
