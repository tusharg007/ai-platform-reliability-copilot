"""Generate realistic synthetic platform logs, deployments, and incidents."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import random

import pandas as pd

from src.config import DEFAULT_ENVIRONMENT, RAW_DATA_DIR, SAMPLE_DATA_DIR, ensure_project_dirs


SEED = 42
DEFAULT_DAYS = 14
INTERVAL_MINUTES = 15
QUICK_DAYS = 3
QUICK_REQUEST_SCALE = 0.38
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
SERVICE_PROFILES = {
    "api-gateway": {
        "base_requests": 36,
        "latency_ms": 95,
        "latency_jitter": 22,
        "error_rate": 0.010,
        "client_error_rate": 0.012,
        "cpu": 54,
        "memory": 58,
        "db_latency": 24,
        "queue_lag": 1.5,
        "criticality_weight": 1.15,
        "regions": [0.40, 0.25, 0.20, 0.15],
        "status_mix": {200: 0.93, 201: 0.03, 400: 0.01, 401: 0.01, 500: 0.01, 503: 0.01},
        "endpoints": ["/v1/search", "/v1/orders", "/v1/login", "/v1/recommendations"],
    },
    "auth-service": {
        "base_requests": 24,
        "latency_ms": 72,
        "latency_jitter": 16,
        "error_rate": 0.004,
        "client_error_rate": 0.020,
        "cpu": 43,
        "memory": 48,
        "db_latency": 16,
        "queue_lag": 0.5,
        "criticality_weight": 0.95,
        "regions": [0.35, 0.20, 0.30, 0.15],
        "status_mix": {200: 0.92, 201: 0.02, 400: 0.01, 401: 0.03, 403: 0.01, 500: 0.01},
        "endpoints": ["/auth/login", "/auth/refresh", "/auth/validate"],
    },
    "payment-service": {
        "base_requests": 14,
        "latency_ms": 148,
        "latency_jitter": 28,
        "error_rate": 0.012,
        "client_error_rate": 0.006,
        "cpu": 57,
        "memory": 61,
        "db_latency": 32,
        "queue_lag": 2.0,
        "criticality_weight": 1.25,
        "regions": [0.30, 0.25, 0.20, 0.25],
        "status_mix": {200: 0.92, 201: 0.02, 400: 0.01, 402: 0.01, 500: 0.02, 502: 0.01, 503: 0.01},
        "endpoints": ["/payments/charge", "/payments/refund", "/payments/status"],
    },
    "recommendation-service": {
        "base_requests": 18,
        "latency_ms": 132,
        "latency_jitter": 24,
        "error_rate": 0.006,
        "client_error_rate": 0.004,
        "cpu": 64,
        "memory": 67,
        "db_latency": 20,
        "queue_lag": 1.0,
        "criticality_weight": 0.90,
        "regions": [0.38, 0.18, 0.24, 0.20],
        "status_mix": {200: 0.95, 400: 0.01, 404: 0.01, 500: 0.02, 503: 0.01},
        "endpoints": ["/recommendations/home", "/recommendations/similar"],
    },
    "database-service": {
        "base_requests": 10,
        "latency_ms": 48,
        "latency_jitter": 10,
        "error_rate": 0.003,
        "client_error_rate": 0.001,
        "cpu": 49,
        "memory": 63,
        "db_latency": 14,
        "queue_lag": 0.2,
        "criticality_weight": 1.20,
        "regions": [0.35, 0.20, 0.20, 0.25],
        "status_mix": {200: 0.97, 400: 0.005, 500: 0.015, 503: 0.01},
        "endpoints": ["/query/orders", "/query/users", "/query/recommendations"],
    },
    "worker-service": {
        "base_requests": 9,
        "latency_ms": 118,
        "latency_jitter": 20,
        "error_rate": 0.007,
        "client_error_rate": 0.001,
        "cpu": 51,
        "memory": 56,
        "db_latency": 18,
        "queue_lag": 6.0,
        "criticality_weight": 1.00,
        "regions": [0.25, 0.20, 0.20, 0.35],
        "status_mix": {200: 0.95, 202: 0.02, 500: 0.015, 503: 0.015},
        "endpoints": ["/jobs/process", "/jobs/retry", "/jobs/drain"],
    },
    "notification-service": {
        "base_requests": 11,
        "latency_ms": 88,
        "latency_jitter": 18,
        "error_rate": 0.008,
        "client_error_rate": 0.002,
        "cpu": 42,
        "memory": 47,
        "db_latency": 10,
        "queue_lag": 2.0,
        "criticality_weight": 0.85,
        "regions": [0.28, 0.18, 0.22, 0.32],
        "status_mix": {200: 0.95, 202: 0.02, 500: 0.01, 502: 0.01, 503: 0.01},
        "endpoints": ["/notify/email", "/notify/push", "/notify/webhook"],
    },
}


@dataclass(frozen=True)
class IncidentSpec:
    incident_id: str
    incident_type: str
    primary_service: str
    affected_services: tuple[str, ...]
    region: str
    start_offset_hours: int
    duration_hours: int
    severity: str
    description: str

    def window(self, end_time: datetime) -> tuple[datetime, datetime]:
        start_time = end_time - timedelta(hours=self.start_offset_hours)
        end_incident = start_time + timedelta(hours=self.duration_hours)
        return start_time, end_incident


@dataclass(frozen=True)
class WeightedSampler:
    values: tuple[object, ...]
    cumulative: tuple[float, ...]

    def pick(self, rng: random.Random) -> object:
        target = rng.random() * self.cumulative[-1]
        for index, boundary in enumerate(self.cumulative):
            if target <= boundary:
                return self.values[index]
        return self.values[-1]


def build_sampler(weighted_values: dict[object, float] | list[float], values: list[object] | None = None) -> WeightedSampler:
    if isinstance(weighted_values, dict):
        items = list(weighted_values.items())
        sample_values = [item[0] for item in items]
        weights = [float(item[1]) for item in items]
    else:
        if values is None:
            raise ValueError("values must be provided when weighted_values is a list")
        sample_values = list(values)
        weights = [float(weight) for weight in weighted_values]

    cumulative: list[float] = []
    running = 0.0
    for weight in weights:
        running += weight
        cumulative.append(running)
    return WeightedSampler(tuple(sample_values), tuple(cumulative))


def build_incident_specs() -> list[IncidentSpec]:
    return [
        IncidentSpec(
            "INC-2001",
            "database timeout",
            "database-service",
            ("database-service", "api-gateway", "payment-service"),
            "us-east-1",
            132,
            9,
            "high",
            "Database latency surge causes upstream timeouts and elevated 5xx responses.",
        ),
        IncidentSpec(
            "INC-2002",
            "deployment regression",
            "api-gateway",
            ("api-gateway", "payment-service"),
            "us-west-2",
            88,
            8,
            "high",
            "A gateway deployment increases error rate and p95 latency immediately after rollout.",
        ),
        IncidentSpec(
            "INC-2003",
            "memory leak",
            "recommendation-service",
            ("recommendation-service",),
            "eu-west-1",
            160,
            20,
            "medium",
            "Heap growth accumulates over many hours before latency and errors worsen.",
        ),
        IncidentSpec(
            "INC-2004",
            "authentication failure spike",
            "auth-service",
            ("auth-service", "api-gateway"),
            "eu-west-1",
            52,
            5,
            "medium",
            "Expired sessions and invalid token validation increase 401 and 403 rates.",
        ),
        IncidentSpec(
            "INC-2005",
            "external API failure",
            "payment-service",
            ("payment-service",),
            "ap-south-1",
            28,
            7,
            "critical",
            "External payment provider instability surfaces as 502 and 503 failures.",
        ),
        IncidentSpec(
            "INC-2006",
            "queue backlog",
            "worker-service",
            ("worker-service", "notification-service"),
            "ap-south-1",
            18,
            10,
            "high",
            "Queue lag rises as worker throughput drops and notifications are delayed.",
        ),
        IncidentSpec(
            "INC-2007",
            "high latency",
            "recommendation-service",
            ("recommendation-service", "api-gateway"),
            "us-east-1",
            74,
            6,
            "medium",
            "CPU-heavy recommendation fan-out increases latency without immediate hard failure.",
        ),
    ]


def build_deployment_schedule(start_time: datetime, end_time: datetime) -> dict[str, list[dict[str, object]]]:
    schedule: dict[str, list[dict[str, object]]] = {}
    for service_name in SERVICE_PROFILES:
        cadence_days = 3 if service_name in {"api-gateway", "payment-service"} else 4
        events = []
        version_counter = 1
        current_time = start_time + timedelta(hours=(len(service_name) * 3) % 24)
        while current_time < end_time + timedelta(hours=1):
            region = REGIONS[(version_counter + len(service_name)) % len(REGIONS)]
            events.append(
                {
                    "service_name": service_name,
                    "deployment_version": f"2026.07.{version_counter}",
                    "event_type": "deploy",
                    "timestamp": current_time.isoformat(),
                    "region": region,
                    "change_summary": f"Synthetic rollout for {service_name} version {version_counter}.",
                }
            )
            current_time += timedelta(days=cadence_days)
            version_counter += 1
        schedule[service_name] = events
    return schedule


def build_deployment_lookup(
    timestamps: pd.DatetimeIndex,
    schedule: dict[str, list[dict[str, object]]],
) -> dict[str, list[tuple[str, datetime]]]:
    lookup: dict[str, list[tuple[str, datetime]]] = {}
    for service_name, events in schedule.items():
        parsed_events = [
            (str(event["deployment_version"]), datetime.fromisoformat(str(event["timestamp"])))
            for event in events
        ]
        event_index = 0
        active_version, active_time = parsed_events[0]
        service_lookup: list[tuple[str, datetime]] = []
        for ts in timestamps:
            ts_py = ts.to_pydatetime()
            while event_index + 1 < len(parsed_events) and parsed_events[event_index + 1][1] <= ts_py:
                event_index += 1
                active_version, active_time = parsed_events[event_index]
            service_lookup.append((active_version, active_time))
        lookup[service_name] = service_lookup
    return lookup


def request_multiplier(ts: datetime, service_name: str) -> float:
    hour = ts.hour + ts.minute / 60
    weekday = ts.weekday()
    business_wave = 1.0 + 0.35 * math.sin((hour - 9) / 24 * 2 * math.pi)
    weekend = 0.82 if weekday >= 5 else 1.0
    service_modifier = 1.12 if service_name in {"api-gateway", "auth-service"} else 0.92 if service_name == "worker-service" else 1.0
    return max(0.45, business_wave * weekend * service_modifier)


def incident_modifiers(
    spec: IncidentSpec,
    service_name: str,
    ts: datetime,
    start_time: datetime,
) -> dict[str, float]:
    if service_name not in spec.affected_services:
        return {}
    elapsed_hours = max(0.0, (ts - start_time).total_seconds() / 3600)
    if spec.incident_type == "database timeout":
        return {"latency": 180, "db_latency": 130, "cpu": 5, "memory": 2, "queue": 1.5, "error_rate": 0.10, "timeout_rate": 0.08}
    if spec.incident_type == "deployment regression":
        return {"latency": 120, "db_latency": 18, "cpu": 10, "memory": 4, "queue": 1.0, "error_rate": 0.08, "timeout_rate": 0.03}
    if spec.incident_type == "memory leak":
        memory_boost = min(28, elapsed_hours * 1.8)
        latency_boost = max(0, (elapsed_hours - 8) * 10)
        error_boost = 0.01 if elapsed_hours < 10 else min(0.07, 0.01 + (elapsed_hours - 10) * 0.006)
        return {"latency": latency_boost, "db_latency": 6, "cpu": 6, "memory": memory_boost, "queue": 0.5, "error_rate": error_boost, "timeout_rate": 0.0}
    if spec.incident_type == "authentication failure spike":
        return {"latency": 18, "db_latency": 2, "cpu": 4, "memory": 1, "queue": 0.0, "error_rate": 0.0, "auth_failure_rate": 0.18}
    if spec.incident_type == "external API failure":
        return {"latency": 95, "db_latency": 5, "cpu": 3, "memory": 1, "queue": 2.5, "error_rate": 0.14, "timeout_rate": 0.02}
    if spec.incident_type == "queue backlog":
        return {"latency": 85, "db_latency": 5, "cpu": 8, "memory": 6, "queue": 22, "error_rate": 0.04, "timeout_rate": 0.01}
    if spec.incident_type == "high latency":
        return {"latency": 110, "db_latency": 8, "cpu": 16, "memory": 3, "queue": 0.8, "error_rate": 0.012, "timeout_rate": 0.01}
    return {}


def select_error_type(service_name: str, spec: IncidentSpec | None, status_code: int) -> tuple[str, str]:
    if spec:
        mapping = {
            "database timeout": ("DATABASE_TIMEOUT", "Downstream database latency exceeded the configured timeout budget."),
            "deployment regression": ("DEPLOYMENT_REGRESSION", "Error rate increased immediately after a new version rollout."),
            "memory leak": ("MEMORY_PRESSURE", "Process memory usage continued to rise beyond the steady-state baseline."),
            "authentication failure spike": ("AUTHENTICATION_FAILURE", "Invalid token or expired session caused authentication rejection."),
            "external API failure": ("UPSTREAM_PROVIDER_FAILURE", "Third-party provider returned unstable 502 or 503 responses."),
            "queue backlog": ("QUEUE_BACKLOG", "Worker queue lag increased and delayed async processing."),
            "high latency": ("LATENCY_SPIKE", "CPU-intensive recommendation fan-out increased end-to-end latency."),
        }
        return mapping[spec.incident_type]

    if service_name == "payment-service" and status_code >= 500:
        return ("PAYMENT_PROCESSOR_ERROR", "Payment provider dependency returned a retryable server error.")
    if service_name == "notification-service" and status_code >= 500:
        return ("NOTIFICATION_PROVIDER_ERROR", "Notification provider returned a transient upstream error.")
    if service_name == "auth-service" and status_code in {401, 403}:
        return ("INVALID_TOKEN", "Authentication request failed due to invalid or expired credentials.")
    if status_code >= 500:
        return ("INTERNAL_SERVER_ERROR", "Unhandled server-side failure occurred during request processing.")
    if status_code >= 400:
        return ("CLIENT_ERROR", "Client-side validation or authorization failure occurred.")
    return ("", "Request completed within the expected service envelope.")


def build_interval_incident_lookup(
    timestamps: pd.DatetimeIndex,
    incident_specs: list[IncidentSpec],
    start_time: datetime,
    end_time: datetime,
) -> tuple[dict[tuple[int, str], list[tuple[IncidentSpec, datetime]]], list[tuple[IncidentSpec, dict[str, object]]]]:
    interval_lookup: dict[tuple[int, str], list[tuple[IncidentSpec, datetime]]] = {}
    incident_rows: list[tuple[IncidentSpec, dict[str, object]]] = []
    for spec in incident_specs:
        incident_start, incident_end = spec.window(end_time)
        if incident_end <= start_time or incident_start >= end_time:
            continue
        incident_rows.append(
            (
                spec,
                {
                "incident_id": spec.incident_id,
                "incident_type": spec.incident_type,
                "primary_service": spec.primary_service,
                "affected_services": ",".join(spec.affected_services),
                "region": spec.region,
                "severity": spec.severity,
                "start_time": incident_start.isoformat(),
                "end_time": incident_end.isoformat(),
                "description": spec.description,
                },
            )
        )
        for index, ts in enumerate(timestamps):
            ts_py = ts.to_pydatetime()
            if incident_start <= ts_py < incident_end:
                interval_lookup.setdefault((index, spec.region), []).append((spec, incident_start))
    return interval_lookup, incident_rows


def build_interval_context(
    service_name: str,
    profile: dict[str, object],
    ts_py: datetime,
    deployment_version: str,
    deployment_time: datetime,
    active_specs: list[tuple[IncidentSpec, datetime]],
) -> dict[str, object]:
    latency_ms = float(profile["latency_ms"])
    cpu_usage = float(profile["cpu"])
    memory_usage = float(profile["memory"])
    db_latency_ms = float(profile["db_latency"])
    queue_lag = float(profile["queue_lag"])
    error_rate = float(profile["error_rate"])
    client_error_rate = float(profile["client_error_rate"])
    timeout_rate = 0.0
    triggering_spec: IncidentSpec | None = None

    for spec, incident_start in active_specs:
        modifier = incident_modifiers(spec, service_name, ts_py, incident_start)
        if not modifier:
            continue
        triggering_spec = spec
        latency_ms += modifier.get("latency", 0.0)
        cpu_usage += modifier.get("cpu", 0.0)
        memory_usage += modifier.get("memory", 0.0)
        db_latency_ms += modifier.get("db_latency", 0.0)
        queue_lag += modifier.get("queue", 0.0)
        error_rate += modifier.get("error_rate", 0.0)
        client_error_rate += modifier.get("auth_failure_rate", 0.0)
        timeout_rate += modifier.get("timeout_rate", 0.0)

    deployment_freshness_hours = (ts_py - deployment_time).total_seconds() / 3600
    if deployment_freshness_hours <= 6 and service_name in {"api-gateway", "payment-service"}:
        latency_ms += 8
        error_rate += 0.003

    return {
        "deployment_version": deployment_version,
        "triggering_spec": triggering_spec,
        "latency_ms": latency_ms,
        "cpu_usage": cpu_usage,
        "memory_usage": memory_usage,
        "db_latency_ms": db_latency_ms,
        "queue_lag": queue_lag,
        "error_rate": error_rate,
        "client_error_rate": client_error_rate,
        "timeout_rate": timeout_rate,
    }


def resolve_status_code(
    service_name: str,
    profile: dict[str, object],
    triggering_spec: IncidentSpec | None,
    client_error_rate: float,
    error_rate: float,
    timeout_rate: float,
    latency_ms: float,
    rng: random.Random,
    status_sampler: WeightedSampler,
) -> int:
    if rng.random() < client_error_rate:
        if service_name == "auth-service":
            status_code = 401 if rng.random() < 0.7 else 403
        elif service_name == "api-gateway":
            status_code = 401 if rng.random() < 0.5 else 400
        else:
            status_code = 400
    elif rng.random() < error_rate:
        if triggering_spec and triggering_spec.incident_type == "external API failure":
            status_code = 502 if rng.random() < 0.65 else 503
        elif triggering_spec and triggering_spec.incident_type == "database timeout":
            status_code = 503 if rng.random() < 0.4 else 504
        elif triggering_spec and triggering_spec.incident_type == "queue backlog":
            status_code = 503 if rng.random() < 0.55 else 500
        else:
            status_code = int(status_sampler.pick(rng))
            if status_code < 500:
                status_code = 500 if rng.random() < 0.6 else 503
    else:
        status_code = int(status_sampler.pick(rng))
        if status_code >= 400 and rng.random() > (client_error_rate + error_rate) * 3:
            status_code = 200

    if rng.random() < timeout_rate and status_code < 500:
        status_code = 504

    if latency_ms > float(profile["latency_ms"]) * 2.3 and status_code == 200 and rng.random() < 0.08:
        status_code = 504

    return status_code


def generate_synthetic_logs(
    days: int = DEFAULT_DAYS,
    seed: int = SEED,
    quick: bool = False,
    output_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ensure_project_dirs()
    rng = random.Random(seed)
    output_root = output_dir or RAW_DATA_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    effective_days = QUICK_DAYS if quick and days == DEFAULT_DAYS else days
    request_scale = QUICK_REQUEST_SCALE if quick else 1.0

    end_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(days=effective_days)
    timestamps = pd.date_range(start=start_time, end=end_time, freq=f"{INTERVAL_MINUTES}min", inclusive="left")

    incident_specs = build_incident_specs()
    deployments = build_deployment_schedule(start_time, end_time)
    deployment_rows = [event for events in deployments.values() for event in events]
    deployment_lookup = build_deployment_lookup(timestamps, deployments)
    interval_incidents, incident_rows = build_interval_incident_lookup(timestamps, incident_specs, start_time, end_time)

    for spec, row in incident_rows:
        start_time_spec = datetime.fromisoformat(str(row["start_time"]))
        deployment_version = deployment_lookup[spec.primary_service][0][0]
        for version, deployed_at in deployment_lookup[spec.primary_service]:
            if deployed_at <= start_time_spec:
                deployment_version = version
            else:
                break
        row["deployment_version"] = deployment_version

    rows: list[dict[str, object]] = []
    region_samplers = {
        service_name: build_sampler(profile["regions"], REGIONS)
        for service_name, profile in SERVICE_PROFILES.items()
    }
    status_samplers = {
        service_name: build_sampler(profile["status_mix"])
        for service_name, profile in SERVICE_PROFILES.items()
    }

    for index, ts in enumerate(timestamps):
        ts_py = ts.to_pydatetime()
        for service_name, profile in SERVICE_PROFILES.items():
            base_requests = float(profile["base_requests"]) * request_scale
            volume_noise = rng.uniform(0.85, 1.18)
            interval_requests = max(3, int(round(base_requests * request_multiplier(ts_py, service_name) * volume_noise)))
            deployment_version, deployment_time = deployment_lookup[service_name][index]
            interval_context_by_region = {
                region: build_interval_context(
                    service_name=service_name,
                    profile=profile,
                    ts_py=ts_py,
                    deployment_version=deployment_version,
                    deployment_time=deployment_time,
                    active_specs=interval_incidents.get((index, region), []),
                )
                for region in REGIONS
            }
            status_sampler = status_samplers[service_name]
            region_sampler = region_samplers[service_name]
            endpoints = profile["endpoints"]

            for _ in range(interval_requests):
                region = str(region_sampler.pick(rng))
                context = interval_context_by_region[region]
                triggering_spec = context["triggering_spec"]
                latency_ms = float(context["latency_ms"]) + rng.gauss(0, float(profile["latency_jitter"]))
                cpu_usage = float(context["cpu_usage"]) + rng.gauss(0, 3)
                memory_usage = float(context["memory_usage"]) + rng.gauss(0, 2.5)
                db_latency_ms = float(context["db_latency_ms"]) + rng.gauss(0, 3.2)
                queue_lag = max(0.0, float(context["queue_lag"]) + rng.gauss(0, 1.2))

                status_code = resolve_status_code(
                    service_name=service_name,
                    profile=profile,
                    triggering_spec=triggering_spec,
                    client_error_rate=float(context["client_error_rate"]),
                    error_rate=float(context["error_rate"]),
                    timeout_rate=float(context["timeout_rate"]),
                    latency_ms=latency_ms,
                    rng=rng,
                    status_sampler=status_sampler,
                )
                error_type, message = select_error_type(service_name, triggering_spec, status_code)
                if status_code < 400 and triggering_spec and triggering_spec.incident_type == "high latency":
                    message = "Service remained available but experienced elevated end-to-end latency."

                rows.append(
                    {
                        "timestamp": (ts_py + timedelta(seconds=rng.randint(0, INTERVAL_MINUTES * 60 - 1))).isoformat(),
                        "service_name": service_name,
                        "environment": DEFAULT_ENVIRONMENT,
                        "log_level": "ERROR" if status_code >= 500 else "WARN" if status_code >= 400 else "INFO",
                        "request_id": f"req-{rng.getrandbits(56):014x}",
                        "trace_id": f"trace-{rng.getrandbits(64):016x}",
                        "endpoint": endpoints[rng.randrange(len(endpoints))],
                        "status_code": int(status_code),
                        "latency_ms": round(max(12.0, latency_ms), 2),
                        "error_type": error_type,
                        "message": message,
                        "cpu_usage": round(min(99.0, max(8.0, cpu_usage)), 2),
                        "memory_usage": round(min(99.0, max(10.0, memory_usage)), 2),
                        "db_latency_ms": round(min(400.0, max(1.0, db_latency_ms)), 2),
                        "queue_lag": round(min(120.0, max(0.0, queue_lag)), 2),
                        "region": region,
                        "deployment_version": str(context["deployment_version"]),
                    }
                )

    logs_df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    deployments_df = pd.DataFrame(deployment_rows).sort_values("timestamp").reset_index(drop=True)
    incidents_df = pd.DataFrame(row for _, row in incident_rows).sort_values("start_time").reset_index(drop=True)

    logs_df.to_csv(output_root / "platform_logs.csv", index=False)
    deployments_df.to_csv(output_root / "deployment_events.csv", index=False)
    incidents_df.to_csv(output_root / "known_incidents.csv", index=False)
    logs_df.head(500).to_csv(SAMPLE_DATA_DIR / "platform_logs_sample.csv", index=False)
    return logs_df, deployments_df, incidents_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic reliability telemetry.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Number of trailing days to synthesize.")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed for reproducible output generation.")
    parser.add_argument("--quick", action="store_true", help="Generate a smaller CI and Render-friendly dataset.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logs_df, deployments_df, incidents_df = generate_synthetic_logs(
        days=args.days,
        seed=args.seed,
        quick=args.quick,
    )
    print(
        "Generated synthetic data:",
        f"logs={len(logs_df)}",
        f"deployments={len(deployments_df)}",
        f"known_incidents={len(incidents_df)}",
        f"days={QUICK_DAYS if args.quick and args.days == DEFAULT_DAYS else args.days}",
        f"mode={'quick' if args.quick else 'default'}",
        f"seed={args.seed}",
    )


if __name__ == "__main__":
    main()
