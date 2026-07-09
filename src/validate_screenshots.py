"""Validate screenshot artifacts for local/demo workflows."""

from __future__ import annotations

from src.config import ASSETS_DIR


def validate_screenshots() -> None:
    required_assets = [
        "dashboard_overview.png",
        "service_health.png",
        "anomaly_detection.png",
        "incident_timeline.png",
        "copilot_assistant.png",
        "model_evaluation.png",
    ]
    for filename in required_assets:
        path = ASSETS_DIR / filename
        if not path.exists() or path.stat().st_size < 20000:
            raise ValueError(f"Missing or undersized screenshot: {filename}")


def main() -> None:
    validate_screenshots()
    print("Screenshot validation passed.")


if __name__ == "__main__":
    main()
