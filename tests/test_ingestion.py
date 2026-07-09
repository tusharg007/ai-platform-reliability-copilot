import pandas as pd

from src.config import PROCESSED_DATA_DIR, REPORTS_DIR


def test_ingestion_outputs_exist():
    assert (PROCESSED_DATA_DIR / "structured_logs.csv").exists()
    assert (PROCESSED_DATA_DIR / "service_hourly_metrics.csv").exists()
    assert (PROCESSED_DATA_DIR / "incident_windows.csv").exists()
    assert (REPORTS_DIR / "data_quality_report.md").exists()


def test_service_hourly_metrics_have_error_rate():
    df = pd.read_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
    assert "error_rate" in df.columns
    assert df["request_count"].min() > 0
    assert {"avg_cpu_usage", "avg_memory_usage", "avg_db_latency_ms", "avg_queue_lag", "status_5xx_rate", "status_4xx_rate"}.issubset(df.columns)
