"""Generate realistic synthetic logs, metrics, and incidents for the demo.

The payment-service/ap-south/v2.1.4 incident is intentionally strong so the
copilot has a crisp story to retrieve, analyze, and explain.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
import random
import uuid


DATA_DIR = Path(__file__).resolve().parent
SERVICES = [
    "auth-service",
    "payment-service",
    "matchmaking-service",
    "player-profile-service",
    "notification-service",
    "game-session-service",
    "leaderboard-service",
]
REGIONS = ["us-east", "us-west", "eu-central", "ap-south"]
ERROR_TYPES = [
    "",
    "AUTH_TOKEN_EXPIRED",
    "DB_CONNECTION_TIMEOUT",
    "UPSTREAM_503",
    "CACHE_MISS_STORM",
    "RATE_LIMIT_EXCEEDED",
    "MATCHMAKING_QUEUE_TIMEOUT",
]
VERSIONS = ["v1.8.2", "v2.0.9", "v2.1.3", "v2.1.4"]


def _now_floor() -> datetime:
    return datetime.now().replace(minute=0, second=0, microsecond=0)


def _is_payment_incident(ts: datetime, service: str, region: str, version: str) -> bool:
    incident_start = _now_floor() - timedelta(hours=4)
    return (
        service == "payment-service"
        and region == "ap-south"
        and version == "v2.1.4"
        and ts >= incident_start
    )


def generate_logs(row_count: int = 12000) -> list[dict[str, object]]:
    random.seed(42)
    end_time = _now_floor()
    start = end_time - timedelta(hours=48)
    step_seconds = int((48 * 60 * 60) / row_count)
    rows: list[dict[str, object]] = []

    for i in range(row_count):
        ts = start + timedelta(seconds=i * step_seconds)
        service = random.choice(SERVICES)
        region = random.choice(REGIONS)
        version = "v2.1.4" if ts > _now_floor() - timedelta(hours=5) else random.choice(VERSIONS[:-1])
        incident = _is_payment_incident(ts, service, region, version)

        if incident:
            is_error = random.random() < 0.38
            status_code = random.choices([200, 500, 503, 504], [0.62, 0.08, 0.18, 0.12])[0]
            latency = max(850, int(random.gauss(1450, 260)))
            error_type = "DB_CONNECTION_TIMEOUT" if is_error or status_code >= 500 else ""
            message = "database connection timeout after deployment v2.1.4"
            request_count = random.randint(40, 95)
        else:
            is_error = random.random() < 0.025
            status_code = random.choices([200, 201, 400, 401, 500, 503], [0.88, 0.05, 0.025, 0.02, 0.015, 0.01])[0]
            latency = max(40, int(random.gauss(230, 85)))
            error_type = random.choice(ERROR_TYPES[1:]) if is_error or status_code >= 500 else ""
            message = "request completed" if status_code < 500 else f"{error_type} observed in service logs"
            request_count = random.randint(20, 140)

        rows.append(
            {
                "timestamp": ts.isoformat(),
                "service_name": service,
                "environment": "production",
                "region": region,
                "status_code": status_code,
                "latency_ms": latency,
                "error_type": error_type,
                "request_count": request_count,
                "trace_id": str(uuid.uuid4()),
                "deployment_version": version,
                "message": message,
            }
        )

    return rows


def generate_metrics(row_count: int = 2400) -> list[dict[str, object]]:
    random.seed(7)
    end_time = _now_floor()
    start = end_time - timedelta(hours=48)
    step_seconds = int((48 * 60 * 60) / row_count)
    rows: list[dict[str, object]] = []

    for i in range(row_count):
        ts = start + timedelta(seconds=i * step_seconds)
        service = SERVICES[i % len(SERVICES)]
        region = REGIONS[(i // len(SERVICES)) % len(REGIONS)]
        version = "v2.1.4" if ts > _now_floor() - timedelta(hours=5) else random.choice(VERSIONS[:-1])
        incident = _is_payment_incident(ts, service, region, version)

        if incident:
            p95_latency = round(random.gauss(1450, 145), 2)
            error_rate = round(random.uniform(0.085, 0.118), 4)
            timeout_count = random.randint(48, 96)
            cpu = round(random.uniform(76, 92), 2)
            memory = round(random.uniform(78, 93), 2)
            request_count = random.randint(1200, 1900)
        else:
            p95_latency = round(max(110, random.gauss(280, 55)), 2)
            error_rate = round(max(0.001, random.gauss(0.015, 0.007)), 4)
            timeout_count = random.randint(0, 8)
            cpu = round(random.uniform(28, 68), 2)
            memory = round(random.uniform(35, 72), 2)
            request_count = random.randint(600, 1600)

        rows.append(
            {
                "timestamp": ts.isoformat(),
                "service_name": service,
                "region": region,
                "cpu_usage": cpu,
                "memory_usage": memory,
                "p95_latency_ms": p95_latency,
                "error_rate": error_rate,
                "request_count": request_count,
                "timeout_count": timeout_count,
                "deployment_version": version,
            }
        )

    return rows


def generate_incidents() -> list[dict[str, object]]:
    ts = (_now_floor() - timedelta(hours=3, minutes=30)).isoformat()
    return [
        {
            "incident_id": "INC-2026-071",
            "timestamp": ts,
            "service_name": "payment-service",
            "severity": "SEV-2",
            "issue_type": "DB_CONNECTION_TIMEOUT",
            "root_cause": "Connection pool saturation after deployment v2.1.4 in ap-south",
            "resolution": "Increase pool limit, verify migrations, rollback if error rate stays above 5%",
            "duration_minutes": 84,
        },
        {
            "incident_id": "INC-2026-068",
            "timestamp": (_now_floor() - timedelta(hours=17)).isoformat(),
            "service_name": "matchmaking-service",
            "severity": "SEV-3",
            "issue_type": "MATCHMAKING_QUEUE_TIMEOUT",
            "root_cause": "Queue consumer lag during regional traffic spike",
            "resolution": "Scaled consumers and drained queue backlog",
            "duration_minutes": 36,
        },
    ]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(DATA_DIR / "synthetic_logs.csv", generate_logs())
    write_csv(DATA_DIR / "service_metrics.csv", generate_metrics())
    write_csv(DATA_DIR / "incidents.csv", generate_incidents())
    print("Generated synthetic_logs.csv, service_metrics.csv, and incidents.csv")


if __name__ == "__main__":
    main()
