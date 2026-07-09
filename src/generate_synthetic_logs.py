"""Generate synthetic platform logs, deployment events, and incident ground truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import uuid

import pandas as pd

from src.config import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_REGIONS,
    DEFAULT_SERVICES,
    RAW_DATA_DIR,
    SAMPLE_DATA_DIR,
    ensure_project_dirs,
)


SEED = 42
LOG_INTERVAL_MINUTES = 5
DEFAULT_DAYS = 14
ERROR_TO_STATUS = {
    "database timeout": 504,
    "memory leak": 500,
    "deployment regression": 503,
    "queue backlog": 503,
    "high latency": 200,
    "authentication failure spike": 401,
    "5xx error spike": 500,
    "external API failure": 502,
}
SERVICE_ENDPOINTS = {
    "api-gateway": ["/v1/search", "/v1/orders", "/v1/login", "/v1/recommendations"],
    "auth-service": ["/auth/login", "/auth/refresh", "/auth/validate"],
    "payment-service": ["/payments/charge", "/payments/refund", "/payments/status"],
    "recommendation-service": ["/recommendations/home", "/recommendations/similar"],
    "database-service": ["/query/orders", "/query/users", "/query/recommendations"],
    "worker-service": ["/jobs/process", "/jobs/retry", "/jobs/drain"],
    "notification-service": ["/notify/email", "/notify/push", "/notify/webhook"],
}
SERVICE_BASELINES = {
    "api-gateway": {"latency_ms": 110, "cpu_usage": 52, "memory_usage": 58, "db_latency_ms": 38, "queue_lag": 4},
    "auth-service": {"latency_ms": 95, "cpu_usage": 48, "memory_usage": 54, "db_latency_ms": 24, "queue_lag": 2},
    "payment-service": {"latency_ms": 145, "cpu_usage": 56, "memory_usage": 60, "db_latency_ms": 46, "queue_lag": 5},
    "recommendation-service": {"latency_ms": 165, "cpu_usage": 61, "memory_usage": 66, "db_latency_ms": 42, "queue_lag": 6},
    "database-service": {"latency_ms": 75, "cpu_usage": 58, "memory_usage": 63, "db_latency_ms": 28, "queue_lag": 1},
    "worker-service": {"latency_ms": 125, "cpu_usage": 53, "memory_usage": 57, "db_latency_ms": 35, "queue_lag": 10},
    "notification-service": {"latency_ms": 105, "cpu_usage": 44, "memory_usage": 50, "db_latency_ms": 18, "queue_lag": 3},
}


@dataclass(frozen=True)
class IncidentSpec:
    incident_id: str
    incident_type: str
    primary_service: str
    affected_services: tuple[str, ...]
    start_offset_hours: int
    duration_hours: int
    deployment_version: str
    region: str
    severity: str
    description: str

    def start_time(self, end_time: datetime) -> datetime:
        return end_time - timedelta(hours=self.start_offset_hours)

    def end_time(self, end_time: datetime) -> datetime:
        return self.start_time(end_time) + timedelta(hours=self.duration_hours)


def build_incident_specs() -> list[IncidentSpec]:
    return [
        IncidentSpec("INC-1001", "database timeout", "database-service", ("database-service", "payment-service", "api-gateway"), 260, 10, "2026.07.1", "us-east-1", "high", "Primary database latency spike cascades into upstream timeouts."),
        IncidentSpec("INC-1002", "memory leak", "recommendation-service", ("recommendation-service",), 210, 18, "2026.07.2", "eu-west-1", "medium", "Memory rises steadily until restart pressure appears."),
        IncidentSpec("INC-1003", "deployment regression", "api-gateway", ("api-gateway", "payment-service"), 168, 12, "2026.07.3", "us-west-2", "high", "New gateway release increases 5xx responses and latency."),
        IncidentSpec("INC-1004", "queue backlog", "worker-service", ("worker-service", "notification-service"), 130, 16, "2026.07.2", "ap-south-1", "medium", "Consumer lag grows and downstream notifications slow."),
        IncidentSpec("INC-1005", "high latency", "api-gateway", ("api-gateway", "recommendation-service"), 96, 8, "2026.07.4", "us-east-1", "medium", "High CPU and fan-out latency elevate p95 response times."),
        IncidentSpec("INC-1006", "authentication failure spike", "auth-service", ("auth-service", "api-gateway"), 72, 6, "2026.07.4", "eu-west-1", "medium", "Invalid token verification path triggers elevated 401/403s."),
        IncidentSpec("INC-1007", "5xx error spike", "payment-service", ("payment-service",), 48, 8, "2026.07.5", "us-west-2", "high", "Payment processor errors elevate server-side failures."),
        IncidentSpec("INC-1008", "external API failure", "notification-service", ("notification-service", "worker-service"), 24, 10, "2026.07.5", "ap-south-1", "medium", "Third-party notification provider becomes unstable."),
    ]


def _window_modifier(spec: IncidentSpec, service: str) -> dict[str, float]:
    if service not in spec.affected_services:
        return {}
    if spec.incident_type == "database timeout":
        return {"latency_boost": 380, "db_latency_boost": 220, "error_rate": 0.24, "cpu_boost": 8, "memory_boost": 4, "queue_boost": 6}
    if spec.incident_type == "memory leak":
        return {"latency_boost": 120, "db_latency_boost": 35, "error_rate": 0.07, "cpu_boost": 12, "memory_boost": 26, "queue_boost": 2}
    if spec.incident_type == "deployment regression":
        return {"latency_boost": 280, "db_latency_boost": 45, "error_rate": 0.19, "cpu_boost": 15, "memory_boost": 9, "queue_boost": 4}
    if spec.incident_type == "queue backlog":
        return {"latency_boost": 190, "db_latency_boost": 15, "error_rate": 0.12, "cpu_boost": 10, "memory_boost": 7, "queue_boost": 38}
    if spec.incident_type == "high latency":
        return {"latency_boost": 260, "db_latency_boost": 20, "error_rate": 0.04, "cpu_boost": 24, "memory_boost": 6, "queue_boost": 2}
    if spec.incident_type == "authentication failure spike":
        return {"latency_boost": 75, "db_latency_boost": 10, "error_rate": 0.18, "cpu_boost": 7, "memory_boost": 3, "queue_boost": 0}
    if spec.incident_type == "5xx error spike":
        return {"latency_boost": 210, "db_latency_boost": 40, "error_rate": 0.23, "cpu_boost": 13, "memory_boost": 5, "queue_boost": 4}
    if spec.incident_type == "external API failure":
        return {"latency_boost": 160, "db_latency_boost": 12, "error_rate": 0.11, "cpu_boost": 8, "memory_boost": 4, "queue_boost": 12}
    return {}


def _incident_error_type(incident_type: str) -> str:
    return incident_type.upper().replace(" ", "_")


def _status_for_row(incident_type: str, rng: random.Random) -> int:
    if incident_type == "authentication failure spike":
        return 403 if rng.random() < 0.35 else 401
    if incident_type == "high latency":
        return 200 if rng.random() < 0.88 else 504
    return ERROR_TO_STATUS[incident_type]


def generate_synthetic_logs(days: int = DEFAULT_DAYS, output_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ensure_project_dirs()
    rng = random.Random(SEED)
    output_root = output_dir or RAW_DATA_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    end_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, end=end_time, freq=f"{LOG_INTERVAL_MINUTES}min", inclusive="left")
    incidents = build_incident_specs()

    deployment_rows: list[dict[str, object]] = []
    for service in DEFAULT_SERVICES:
        for day_index in range(days):
            deployment_rows.append(
                {
                    "service_name": service,
                    "deployment_version": f"2026.07.{(day_index % 5) + 1}",
                    "event_type": "deploy",
                    "timestamp": (start_time + timedelta(days=day_index, hours=(day_index * 3) % 24)).isoformat(),
                    "region": DEFAULT_REGIONS[day_index % len(DEFAULT_REGIONS)],
                    "change_summary": f"Scheduled synthetic deployment for {service}.",
                }
            )

    log_rows: list[dict[str, object]] = []
    for ts in timestamps:
        for service in DEFAULT_SERVICES:
            baseline = SERVICE_BASELINES[service]
            region = DEFAULT_REGIONS[(ts.hour + len(service)) % len(DEFAULT_REGIONS)]
            deployment_version = f"2026.07.{((ts.day + len(service)) % 5) + 1}"
            endpoint = SERVICE_ENDPOINTS[service][(ts.hour + ts.minute + len(service)) % len(SERVICE_ENDPOINTS[service])]

            latency_ms = baseline["latency_ms"] + rng.gauss(0, 18)
            cpu_usage = baseline["cpu_usage"] + rng.gauss(0, 4)
            memory_usage = baseline["memory_usage"] + rng.gauss(0, 3)
            db_latency_ms = baseline["db_latency_ms"] + rng.gauss(0, 6)
            queue_lag = max(0, baseline["queue_lag"] + rng.gauss(0, 2))
            status_code = 200
            error_type = ""
            message = "Request completed within expected latency envelope."

            for spec in incidents:
                if spec.region != region:
                    continue
                if not (spec.start_time(end_time) <= ts.to_pydatetime() < spec.end_time(end_time)):
                    continue
                modifier = _window_modifier(spec, service)
                if not modifier:
                    continue
                deployment_version = spec.deployment_version
                latency_ms += modifier["latency_boost"]
                cpu_usage += modifier["cpu_boost"]
                memory_usage += modifier["memory_boost"]
                db_latency_ms += modifier["db_latency_boost"]
                queue_lag += modifier["queue_boost"]
                if rng.random() < modifier["error_rate"]:
                    status_code = _status_for_row(spec.incident_type, rng)
                    error_type = _incident_error_type(spec.incident_type)
                message = spec.description
                if spec.incident_type == "memory leak":
                    elapsed_hours = max(0.0, (ts.to_pydatetime() - spec.start_time(end_time)).total_seconds() / 3600)
                    memory_usage += elapsed_hours * 1.4
                if spec.incident_type == "deployment regression":
                    latency_ms += 35
                    if service in {"api-gateway", "payment-service"} and rng.random() < 0.12:
                        status_code = 503
                        error_type = "DEPLOYMENT_REGRESSION"

            if service == "auth-service" and status_code == 200 and rng.random() < 0.01:
                status_code = 401
                error_type = "INVALID_CREDENTIALS"
                message = "Authentication rejected due to invalid credentials."

            if service == "database-service" and db_latency_ms > 180 and rng.random() < 0.18:
                status_code = 504
                error_type = "DATABASE_TIMEOUT"
                message = "Database query exceeded timeout budget."

            if latency_ms > 430 and status_code == 200 and rng.random() < 0.08:
                status_code = 504
                error_type = error_type or "HIGH_LATENCY_TIMEOUT"
                message = "Request timed out after upstream latency regression."

            log_level = "ERROR" if status_code >= 500 else "WARN" if status_code >= 400 else "INFO"
            trace_id = f"trace-{uuid.uuid4().hex[:12]}"
            request_id = f"req-{uuid.uuid4().hex[:10]}"

            log_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "service_name": service,
                    "environment": DEFAULT_ENVIRONMENT,
                    "log_level": log_level,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "endpoint": endpoint,
                    "status_code": int(status_code),
                    "latency_ms": round(max(20.0, latency_ms), 2),
                    "error_type": error_type,
                    "message": message,
                    "cpu_usage": round(min(99.0, max(5.0, cpu_usage)), 2),
                    "memory_usage": round(min(99.0, max(10.0, memory_usage)), 2),
                    "db_latency_ms": round(max(1.0, db_latency_ms), 2),
                    "queue_lag": round(max(0.0, queue_lag), 2),
                    "region": region,
                    "deployment_version": deployment_version,
                }
            )

    incidents_rows = []
    for spec in incidents:
        incidents_rows.append(
            {
                "incident_id": spec.incident_id,
                "incident_type": spec.incident_type,
                "primary_service": spec.primary_service,
                "affected_services": ",".join(spec.affected_services),
                "region": spec.region,
                "severity": spec.severity,
                "start_time": spec.start_time(end_time).isoformat(),
                "end_time": spec.end_time(end_time).isoformat(),
                "deployment_version": spec.deployment_version,
                "description": spec.description,
            }
        )

    logs_df = pd.DataFrame(log_rows).sort_values("timestamp").reset_index(drop=True)
    deployments_df = pd.DataFrame(deployment_rows).sort_values("timestamp").reset_index(drop=True)
    incidents_df = pd.DataFrame(incidents_rows).sort_values("start_time").reset_index(drop=True)

    logs_df.to_csv(output_root / "platform_logs.csv", index=False)
    deployments_df.to_csv(output_root / "deployment_events.csv", index=False)
    incidents_df.to_csv(output_root / "known_incidents.csv", index=False)
    logs_df.head(250).to_csv(SAMPLE_DATA_DIR / "platform_logs_sample.csv", index=False)

    return logs_df, deployments_df, incidents_df


def main() -> None:
    logs_df, deployments_df, incidents_df = generate_synthetic_logs()
    print(
        "Generated synthetic data:",
        f"logs={len(logs_df)}",
        f"deployments={len(deployments_df)}",
        f"known_incidents={len(incidents_df)}",
    )


if __name__ == "__main__":
    main()
