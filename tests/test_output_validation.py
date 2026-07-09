import pandas as pd

from src.config import ASSETS_DIR, PREDICTIONS_DIR, PROCESSED_DATA_DIR
from src.validate_screenshots import validate_screenshots


def test_risk_scores_are_varied():
    df = pd.read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")
    assert df["risk_score"].nunique() > 1
    assert not (df["risk_score"] == 100).all()
    assert float(df["risk_score"].max() - df["risk_score"].min()) >= 20
    assert df["risk_band"].nunique() >= 3


def test_alerts_and_incidents_are_meaningful():
    alerts = pd.read_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
    incidents = pd.read_csv(PREDICTIONS_DIR / "incidents.csv")
    metrics = pd.read_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
    assert not alerts.empty
    assert not incidents.empty
    assert alerts["alert_type"].nunique() >= 3
    assert metrics["error_rate"].max() > 0


def test_screenshots_exist_and_are_non_empty():
    validate_screenshots()
