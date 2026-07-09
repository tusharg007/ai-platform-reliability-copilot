import pandas as pd

from src.config import RAW_DATA_DIR


def test_raw_log_files_exist():
    assert (RAW_DATA_DIR / "platform_logs.csv").exists()
    assert (RAW_DATA_DIR / "deployment_events.csv").exists()
    assert (RAW_DATA_DIR / "known_incidents.csv").exists()


def test_generated_logs_have_required_columns():
    df = pd.read_csv(RAW_DATA_DIR / "platform_logs.csv")
    required = {
        "timestamp",
        "service_name",
        "environment",
        "log_level",
        "request_id",
        "trace_id",
        "endpoint",
        "status_code",
        "latency_ms",
        "error_type",
        "message",
        "cpu_usage",
        "memory_usage",
        "db_latency_ms",
        "queue_lag",
        "region",
        "deployment_version",
    }
    assert required.issubset(df.columns)
    assert df["service_name"].nunique() == 7
