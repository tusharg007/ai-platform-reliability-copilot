"""Streaming telemetry ingestion pipeline.

Handles real-time ingestion of:
  - Webhook events from Grafana / Datadog / PagerDuty alerting
  - Prometheus-formatted metric scrapes
  - Direct log event POSTs (structured JSON)

For Kafka-based ingestion, install aiokafka and set KAFKA_ENABLED=true.
Everything degrades gracefully to HTTP-only mode without Kafka.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from backend.utils.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])
KAFKA_LOG_TOPIC = "platform.logs"
KAFKA_METRIC_TOPIC = "platform.metrics"
KAFKA_RETRY_SECONDS = 5


# ─────────────────────────────────────────────────────────────────────────────
#  Pydantic Schemas for Ingestion Payloads
# ─────────────────────────────────────────────────────────────────────────────

class LogEvent(BaseModel):
    """A structured log event from a microservice."""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    service_name: str
    region: str
    status_code: int
    latency_ms: float
    error_type: str | None = None
    message: str | None = None
    trace_id: str | None = None
    deployment_version: str | None = None
    environment: str = "production"
    request_count: int = 1


class MetricEvent(BaseModel):
    """A metrics sample from a service."""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    service_name: str
    region: str
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    p95_latency_ms: float = 0.0
    error_rate: float = 0.0
    request_count: int = 0
    timeout_count: int = 0
    deployment_version: str | None = None


class AlertWebhook(BaseModel):
    """Generic webhook payload from Grafana / Datadog / PagerDuty."""
    source: str  # "grafana" | "datadog" | "pagerduty" | "custom"
    alert_name: str
    state: str  # "alerting" | "resolved" | "ok"
    severity: str | None = None
    service_name: str | None = None
    region: str | None = None
    message: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
#  Stream Processor (Windowed Aggregation)
# ─────────────────────────────────────────────────────────────────────────────

class StreamProcessor:
    """Processes incoming telemetry events and computes rolling window aggregates.

    Kafka and HTTP events share an in-memory buffer of recent telemetry for
    anomaly detection queries.
    """

    _instance: "StreamProcessor | None" = None

    def __init__(self, buffer_size: int = 5_000) -> None:
        self._log_buffer: list[dict] = []
        self._metric_buffer: list[dict] = []
        self._alert_buffer: list[dict] = []
        self._buffer_size = buffer_size
        self._event_count = 0
        self.kafka_connected = False

    @classmethod
    def get(cls) -> "StreamProcessor":
        """Return the singleton StreamProcessor instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def ingest_log(self, event: LogEvent) -> None:
        """Add a log event to the in-memory buffer."""
        data = event.model_dump()
        self._log_buffer.append(data)
        if len(self._log_buffer) > self._buffer_size:
            self._log_buffer = self._log_buffer[-self._buffer_size:]
        self._event_count += 1

    def ingest_metric(self, event: MetricEvent) -> None:
        """Add a metric event to the in-memory buffer."""
        data = event.model_dump()
        self._metric_buffer.append(data)
        if len(self._metric_buffer) > self._buffer_size:
            self._metric_buffer = self._metric_buffer[-self._buffer_size:]

    def ingest_alert(self, event: AlertWebhook) -> None:
        """Add an alert webhook to the in-memory buffer."""
        data = event.model_dump()
        data["received_at"] = datetime.utcnow().isoformat()
        self._alert_buffer.append(data)
        if len(self._alert_buffer) > self._buffer_size:
            self._alert_buffer = self._alert_buffer[-self._buffer_size:]
        logger.info(
            "Alert ingested: %s state=%s svc=%s",
            event.alert_name, event.state, event.service_name
        )

    def get_recent_logs(self, service_name: str | None = None,
                         region: str | None = None, limit: int = 500) -> list[dict]:
        """Return recent buffered log events, optionally filtered."""
        events = self._log_buffer[-limit:]
        if service_name:
            events = [e for e in events if e.get("service_name") == service_name]
        if region:
            events = [e for e in events if e.get("region") == region]
        return events

    def get_recent_metrics(self, service_name: str | None = None,
                            region: str | None = None, limit: int = 200) -> list[dict]:
        """Return recent buffered metric events, optionally filtered."""
        events = self._metric_buffer[-limit:]
        if service_name:
            events = [e for e in events if e.get("service_name") == service_name]
        if region:
            events = [e for e in events if e.get("region") == region]
        return events

    def get_active_alerts(self) -> list[dict]:
        """Return alerts that are currently in alerting state (not resolved)."""
        alerting = [
            a for a in self._alert_buffer
            if a.get("state") == "alerting"
        ]
        # Deduplicate by alert_name+service
        seen: set[str] = set()
        unique: list[dict] = []
        for alert in reversed(alerting):
            key = f"{alert.get('alert_name')}:{alert.get('service_name')}"
            if key not in seen:
                seen.add(key)
                unique.append(alert)
        return unique

    def stats(self) -> dict:
        """Return current buffer statistics."""
        return {
            "total_events_ingested": self._event_count,
            "log_buffer_size": len(self._log_buffer),
            "metric_buffer_size": len(self._metric_buffer),
            "active_alerts": len(self.get_active_alerts()),
            "kafka_connected": self.kafka_connected,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Kafka Consumer
# ─────────────────────────────────────────────────────────────────────────────

def _create_kafka_consumer(bootstrap_servers: str):
    from aiokafka import AIOKafkaConsumer

    return AIOKafkaConsumer(
        KAFKA_LOG_TOPIC,
        KAFKA_METRIC_TOPIC,
        bootstrap_servers=bootstrap_servers,
        group_id="reliability-copilot",
        auto_offset_reset="earliest",
    )


def _ingest_kafka_message(message: Any, processor: StreamProcessor) -> None:
    """Validate one Kafka record and pass it through the HTTP ingestion path."""
    try:
        payload = json.loads(message.value)
        if message.topic == KAFKA_LOG_TOPIC:
            processor.ingest_log(LogEvent.model_validate(payload))
        elif message.topic == KAFKA_METRIC_TOPIC:
            processor.ingest_metric(MetricEvent.model_validate(payload))
        else:
            logger.warning("Ignoring unexpected Kafka topic: %s", message.topic)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning("Skipping invalid Kafka record on %s (%s)", message.topic, type(exc).__name__)


async def consume_kafka(bootstrap_servers: str, processor: StreamProcessor) -> None:
    """Consume telemetry continuously, reconnecting after broker failures."""
    while True:
        consumer = None
        try:
            consumer = _create_kafka_consumer(bootstrap_servers)
            await consumer.start()
            processor.kafka_connected = True
            logger.info("Kafka consumer connected to %s", bootstrap_servers)
            async for message in consumer:
                _ingest_kafka_message(message, processor)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Kafka consumer failed; reconnecting")
        finally:
            processor.kafka_connected = False
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    logger.exception("Failed to stop Kafka consumer")
        await asyncio.sleep(KAFKA_RETRY_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
#  Ingestion API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/logs", summary="Ingest structured log events")
async def ingest_logs(
    events: list[LogEvent],
    background_tasks: BackgroundTasks,
) -> dict:
    """Accept a batch of structured log events for real-time processing.

    In production, events arrive via Kafka consumer. This HTTP endpoint
    provides a direct ingestion path for services that cannot use Kafka.
    """
    processor = StreamProcessor.get()
    for event in events:
        background_tasks.add_task(processor.ingest_log, event)
    return {"accepted": len(events), "status": "queued"}


@router.post("/metrics", summary="Ingest metric samples")
async def ingest_metrics(
    events: list[MetricEvent],
    background_tasks: BackgroundTasks,
) -> dict:
    """Accept a batch of metric samples for anomaly detection processing."""
    processor = StreamProcessor.get()
    for event in events:
        background_tasks.add_task(processor.ingest_metric, event)
    return {"accepted": len(events), "status": "queued"}


@router.post("/alert", summary="Receive alert webhook")
async def receive_alert(event: AlertWebhook) -> dict:
    """Accept an alert webhook from Grafana, Datadog, PagerDuty, or custom sources."""
    processor = StreamProcessor.get()
    processor.ingest_alert(event)
    return {
        "status": "received",
        "alert_name": event.alert_name,
        "state": event.state,
        "active_alerts": len(processor.get_active_alerts()),
    }


@router.get("/stats", summary="Ingestion pipeline statistics")
async def ingestion_stats() -> dict:
    """Return current ingestion buffer statistics."""
    return StreamProcessor.get().stats()
