import pandas as pd

from src.config import PREDICTIONS_DIR


def test_clustered_incidents_exist():
    assert (PREDICTIONS_DIR / "incidents.csv").exists()


def test_clustered_incidents_have_recommendations():
    df = pd.read_csv(PREDICTIONS_DIR / "incidents.csv")
    assert {"incident_id", "primary_service", "suspected_root_cause", "recommended_next_steps"}.issubset(df.columns)
    assert len(df) > 0
