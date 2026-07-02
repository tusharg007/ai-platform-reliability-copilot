"""Metric anomaly detection using rolling statistics and optional Isolation Forest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.utils.config import DATA_DIR

try:
    from sklearn.ensemble import IsolationForest
except Exception:  # pragma: no cover - optional dependency fallback
    IsolationForest = None  # type: ignore


METRICS_PATH = DATA_DIR / "service_metrics.csv"


class AnomalyDetector:
    def __init__(self, metrics_path: Path = METRICS_PATH) -> None:
        self.metrics_path = metrics_path

    def load_metrics(self) -> pd.DataFrame:
        if not self.metrics_path.exists():
            return pd.DataFrame()
        df = pd.read_csv(self.metrics_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.sort_values("timestamp")

    def _service_metrics(self, service_name: str, region: str | None = None) -> pd.DataFrame:
        df = self.load_metrics()
        if df.empty:
            return df
        df = df[df["service_name"] == service_name]
        if region:
            df = df[df["region"] == region]
        return df.copy()

    def _detect_metric(self, service_name: str, metric: str, region: str | None = None) -> list[dict[str, Any]]:
        df = self._service_metrics(service_name, region)
        if df.empty or metric not in df:
            return []

        df = df.sort_values("timestamp").copy()
        baseline = df[metric].rolling(window=24, min_periods=8).mean()
        spread = df[metric].rolling(window=24, min_periods=8).std().replace(0, np.nan)
        z_score = (df[metric] - baseline) / spread
        threshold = 3.0 if metric != "error_rate" else 2.5
        candidates = df[(z_score >= threshold) | self._threshold_mask(df, metric)].copy()
        candidates["baseline_value"] = baseline.loc[candidates.index].fillna(df[metric].median())
        candidates["z_score"] = z_score.loc[candidates.index].fillna(0)

        if IsolationForest is not None and len(df) >= 40:
            model = IsolationForest(contamination=0.05, random_state=42)
            flags = model.fit_predict(df[[metric]].fillna(df[metric].median()))
            iso_mask = (flags == -1) & (df[metric] >= df[metric].median() * 1.25)
            iso_idx = df.index[iso_mask]
            candidates = pd.concat([candidates, df.loc[iso_idx]]).drop_duplicates()
            candidates["baseline_value"] = candidates.get("baseline_value", df[metric].median()).fillna(df[metric].median())
            candidates["z_score"] = candidates.get("z_score", 0).fillna(0)

        anomalies = []
        for _, row in candidates.tail(12).iterrows():
            observed = float(row[metric])
            baseline_value = float(row.get("baseline_value", df[metric].median()))
            severity = "high" if observed > baseline_value * 2 or metric == "error_rate" and observed > 0.07 else "medium"
            anomalies.append(
                {
                    "metric_name": metric,
                    "anomaly_timestamp": row["timestamp"].isoformat(),
                    "observed_value": round(observed, 4),
                    "baseline_value": round(baseline_value, 4),
                    "severity": severity,
                    "explanation": f"{metric} deviated from rolling baseline for {service_name} in {row.get('region')}.",
                    "region": row.get("region"),
                    "deployment_version": row.get("deployment_version"),
                }
            )
        return anomalies

    @staticmethod
    def _threshold_mask(df: pd.DataFrame, metric: str) -> pd.Series:
        if metric == "p95_latency_ms":
            return df[metric] >= 900
        if metric == "error_rate":
            return df[metric] >= 0.05
        if metric in {"cpu_usage", "memory_usage"}:
            return df[metric] >= 85
        if metric == "request_count":
            return df[metric] >= df[metric].quantile(0.97)
        if metric == "timeout_count":
            return df[metric] >= 25
        return pd.Series(False, index=df.index)

    def detect_latency_anomalies(self, service_name: str, region: str | None = None) -> list[dict[str, Any]]:
        return self._detect_metric(service_name, "p95_latency_ms", region)

    def detect_error_rate_anomalies(self, service_name: str, region: str | None = None) -> list[dict[str, Any]]:
        return self._detect_metric(service_name, "error_rate", region)

    def detect_cpu_memory_anomalies(self, service_name: str, region: str | None = None) -> list[dict[str, Any]]:
        return self._detect_metric(service_name, "cpu_usage", region) + self._detect_metric(service_name, "memory_usage", region)

    def detect_request_volume_anomalies(self, service_name: str, region: str | None = None) -> list[dict[str, Any]]:
        return self._detect_metric(service_name, "request_count", region) + self._detect_metric(service_name, "timeout_count", region)

    def detect(self, service_name: str, metric_name: str | None = None, region: str | None = None) -> list[dict[str, Any]]:
        if metric_name:
            return self._detect_metric(service_name, metric_name, region)
        return (
            self.detect_latency_anomalies(service_name, region)
            + self.detect_error_rate_anomalies(service_name, region)
            + self.detect_cpu_memory_anomalies(service_name, region)
            + self.detect_request_volume_anomalies(service_name, region)
        )

    def get_service_health_score(self, service_name: str, region: str | None = None) -> float:
        anomalies = self.detect(service_name, region=region)
        high = sum(1 for item in anomalies if item["severity"] == "high")
        medium = sum(1 for item in anomalies if item["severity"] == "medium")
        return max(0.0, round(100 - high * 15 - medium * 3, 2))
