"""Shared paths and runtime constants for the reliability copilot."""

from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
PREDICTIONS_DIR = DATA_DIR / "predictions"
SAMPLE_DATA_DIR = DATA_DIR / "sample"
RUNBOOKS_DIR = ROOT_DIR / "runbooks"
REPORTS_DIR = ROOT_DIR / "reports"
ASSETS_DIR = ROOT_DIR / "assets"

DEFAULT_ENVIRONMENT = "prod-simulated"
DEFAULT_REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
DEFAULT_SERVICES = [
    "api-gateway",
    "auth-service",
    "payment-service",
    "recommendation-service",
    "database-service",
    "worker-service",
    "notification-service",
]


def ensure_project_dirs() -> None:
    for directory in [
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        PREDICTIONS_DIR,
        SAMPLE_DATA_DIR,
        RUNBOOKS_DIR,
        REPORTS_DIR,
        ASSETS_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
