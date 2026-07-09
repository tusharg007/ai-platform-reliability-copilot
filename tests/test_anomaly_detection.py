import pandas as pd

from src.config import PREDICTIONS_DIR


def test_anomaly_outputs_exist():
    assert (PREDICTIONS_DIR / "anomaly_scores.csv").exists()
    assert (PREDICTIONS_DIR / "reliability_alerts.csv").exists()


def test_alerts_have_expected_columns():
    df = pd.read_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
    assert {"alert_id", "service_name", "severity", "alert_type", "anomaly_reason"}.issubset(df.columns)
    assert len(df) > 0
