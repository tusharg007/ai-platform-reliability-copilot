"""Run a lightweight end-to-end verification of the local pipeline."""

from __future__ import annotations

from src.capture_screenshots import capture_screenshots
from src.copilot import answer_question, render_sample_outputs
from src.detect_anomalies import detect_anomalies
from src.evaluate_system import evaluate_system
from src.generate_synthetic_logs import generate_synthetic_logs
from src.incident_clustering import cluster_incidents
from src.ingest_logs import ingest_logs
from src.service_risk_scoring import score_services
from src.validate_outputs import validate_outputs


def main() -> None:
    generate_synthetic_logs()
    ingest_logs()
    detect_anomalies()
    cluster_incidents()
    score_services()
    evaluate_system()
    render_sample_outputs()
    screenshots = capture_screenshots()
    validate_outputs()
    response = answer_question("Why did the database timeout propagate to upstream services?")

    assert response["Likely cause"]
    assert screenshots
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
