"""Small SQLite loader for CSV-backed demo data."""

from pathlib import Path
import sqlite3

import pandas as pd

from backend.utils.config import DATA_DIR


DB_PATH = DATA_DIR / "platform_reliability.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def load_csv_to_sqlite(csv_path: Path, table_name: str) -> int:
    if not csv_path.exists():
        return 0
    df = pd.read_csv(csv_path)
    try:
        with get_connection() as conn:
            df.to_sql(table_name, conn, if_exists="replace", index=False)
    except sqlite3.OperationalError:
        # Some sandboxed demo environments make the data directory read-only.
        # CSV-backed analytics still work, so startup should not fail.
        return -1
    return len(df)


def initialize_database() -> dict[str, int]:
    return {
        "logs": load_csv_to_sqlite(DATA_DIR / "synthetic_logs.csv", "logs"),
        "metrics": load_csv_to_sqlite(DATA_DIR / "service_metrics.csv", "metrics"),
        "incidents": load_csv_to_sqlite(DATA_DIR / "incidents.csv", "incidents"),
    }
