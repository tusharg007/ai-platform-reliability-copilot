"""Log analytics for synthetic backend service telemetry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backend.utils.config import DATA_DIR


LOGS_PATH = DATA_DIR / "synthetic_logs.csv"


def _empty_logs() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp",
            "service_name",
            "environment",
            "region",
            "status_code",
            "latency_ms",
            "error_type",
            "request_count",
            "trace_id",
            "deployment_version",
            "message",
        ]
    )


class LogAnalyzer:
    def __init__(self, logs_path: Path = LOGS_PATH) -> None:
        self.logs_path = logs_path

    def load_logs(self) -> pd.DataFrame:
        if not self.logs_path.exists():
            return _empty_logs()
        df = pd.read_csv(self.logs_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def filter_logs(
        self,
        service_name: str | None = None,
        region: str | None = None,
        status_code: int | None = None,
    ) -> pd.DataFrame:
        df = self.load_logs()
        if service_name:
            df = df[df["service_name"] == service_name]
        if region:
            df = df[df["region"] == region]
        if status_code:
            df = df[df["status_code"] == status_code]
        return df

    def summarize_errors(self, service_name: str | None = None, region: str | None = None) -> dict[str, Any]:
        df = self.filter_logs(service_name, region)
        if df.empty:
            return {"total_logs": 0, "error_count": 0, "error_rate": 0.0, "top_errors": []}
        errors = df[df["status_code"] >= 500]
        top = (
            errors["error_type"]
            .replace("", "UNKNOWN")
            .fillna("UNKNOWN")
            .value_counts()
            .head(5)
            .reset_index()
        )
        top.columns = ["error_type", "count"]
        return {
            "total_logs": int(len(df)),
            "error_count": int(len(errors)),
            "error_rate": round(float(len(errors) / len(df)), 4),
            "top_errors": top.to_dict(orient="records"),
        }

    def calculate_error_rate(self, service_name: str, region: str | None = None) -> float:
        return float(self.summarize_errors(service_name, region)["error_rate"])

    def calculate_latency_summary(self, service_name: str, region: str | None = None) -> dict[str, float]:
        df = self.filter_logs(service_name, region)
        if df.empty:
            return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "avg": round(float(df["latency_ms"].mean()), 2),
            "p50": round(float(df["latency_ms"].quantile(0.50)), 2),
            "p95": round(float(df["latency_ms"].quantile(0.95)), 2),
            "max": round(float(df["latency_ms"].max()), 2),
        }

    def find_top_error_types(self, service_name: str | None = None, region: str | None = None) -> list[dict[str, Any]]:
        df = self.filter_logs(service_name, region)
        errors = df[(df["status_code"] >= 500) & (df["error_type"].fillna("") != "")]
        if errors.empty:
            return []
        top = errors["error_type"].value_counts().head(8).reset_index()
        top.columns = ["error_type", "count"]
        return top.to_dict(orient="records")

    def identify_deployment_related_failures(self, service_name: str, region: str | None = None) -> list[dict[str, Any]]:
        df = self.filter_logs(service_name, region)
        if df.empty:
            return []
        grouped = (
            df.assign(is_error=df["status_code"] >= 500)
            .groupby(["deployment_version", "region"], as_index=False)
            .agg(total=("status_code", "count"), errors=("is_error", "sum"), p95_latency=("latency_ms", lambda s: s.quantile(0.95)))
        )
        grouped["error_rate"] = grouped["errors"] / grouped["total"]
        risky = grouped[(grouped["error_rate"] >= 0.05) | (grouped["p95_latency"] >= 800)]
        return risky.sort_values(["error_rate", "p95_latency"], ascending=False).head(10).round(4).to_dict(orient="records")

    def service_list(self) -> list[str]:
        df = self.load_logs()
        return sorted(df["service_name"].dropna().unique().tolist())

    def metrics_summary(self) -> dict[str, Any]:
        df = self.load_logs()
        if df.empty:
            return {"services": [], "kpis": {}}
        service_summary = []
        for service in self.service_list():
            service_df = df[df["service_name"] == service]
            errors = service_df[service_df["status_code"] >= 500]
            service_summary.append(
                {
                    "service_name": service,
                    "avg_latency": round(float(service_df["latency_ms"].mean()), 2),
                    "p95_latency": round(float(service_df["latency_ms"].quantile(0.95)), 2),
                    "error_rate": round(float(len(errors) / len(service_df)), 4),
                    "request_count": int(service_df["request_count"].sum()),
                }
            )
        kpis = {
            "total_services": len(service_summary),
            "average_latency": round(float(df["latency_ms"].mean()), 2),
            "p95_latency": round(float(df["latency_ms"].quantile(0.95)), 2),
            "overall_error_rate": round(float((df["status_code"] >= 500).mean()), 4),
            "most_affected_region": str(df[df["status_code"] >= 500]["region"].mode().iloc[0]) if not df[df["status_code"] >= 500].empty else "n/a",
        }
        return {"services": service_summary, "kpis": kpis}
