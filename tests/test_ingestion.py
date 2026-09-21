"""Kafka ingestion and FastAPI lifecycle checks without a running broker."""

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import aiokafka
import pytest
from fastapi.testclient import TestClient

import backend.ingestion as ingestion
from backend.ingestion import StreamProcessor
from backend.main import app, settings


class FakeConsumer:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.started = threading.Event()
        self.stopped = threading.Event()

    async def start(self):
        self.started.set()

    async def stop(self):
        self.stopped.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            await asyncio.Event().wait()


def kafka_record(topic, payload):
    value = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return SimpleNamespace(topic=topic, value=value)


def test_kafka_consumes_both_topics_and_stops(monkeypatch):
    fake = FakeConsumer([
        kafka_record("platform.logs", {
            "service_name": "payment-service", "region": "ap-south",
            "status_code": 500, "latency_ms": 120.0,
        }),
        kafka_record("platform.logs", b"not json"),
        kafka_record("platform.logs", {"region": "ap-south"}),
        kafka_record("platform.metrics", {
            "service_name": "payment-service", "region": "ap-south",
            "error_rate": 0.2,
        }),
    ])
    monkeypatch.setattr(settings, "kafka_enabled", True)
    monkeypatch.setattr(settings, "kafka_bootstrap_servers", "broker:9092")
    monkeypatch.setattr(StreamProcessor, "_instance", StreamProcessor())
    monkeypatch.setattr(ingestion, "_create_kafka_consumer", lambda servers: fake)

    with TestClient(app) as client:
        assert fake.started.wait(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            stats = client.get("/ingest/stats").json()
            if stats["log_buffer_size"] == stats["metric_buffer_size"] == 1:
                break
            time.sleep(0.01)
        assert stats["log_buffer_size"] == 1
        assert stats["metric_buffer_size"] == 1
        assert stats["kafka_connected"] is True
        assert client.get("/pipeline/status").json()["kafka_enabled"] is True

    assert fake.stopped.wait(timeout=3)
    assert StreamProcessor.get().stats()["kafka_connected"] is False


def test_kafka_consumer_subscribes_to_both_topics(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(aiokafka, "AIOKafkaConsumer", constructor)

    ingestion._create_kafka_consumer("broker:9092")

    constructor.assert_called_once_with(
        "platform.logs",
        "platform.metrics",
        bootstrap_servers="broker:9092",
        group_id="reliability-copilot",
        auto_offset_reset="earliest",
    )


def test_kafka_disabled_keeps_http_only_mode(monkeypatch):
    monkeypatch.setattr(settings, "kafka_enabled", False)
    monkeypatch.setattr(StreamProcessor, "_instance", StreamProcessor())

    def unexpected_consumer(_servers):
        raise AssertionError("Kafka consumer started while disabled")

    monkeypatch.setattr(ingestion, "_create_kafka_consumer", unexpected_consumer)
    with TestClient(app) as client:
        response = client.post("/ingest/metrics", json=[{
            "service_name": "payment-service", "region": "ap-south",
        }])
        assert response.status_code == 200
        stats = client.get("/ingest/stats").json()
        assert stats["metric_buffer_size"] == 1
        assert stats["kafka_connected"] is False


def test_kafka_enabled_requires_bootstrap_servers(monkeypatch):
    monkeypatch.setattr(settings, "kafka_enabled", True)
    monkeypatch.setattr(settings, "kafka_bootstrap_servers", " ")

    with pytest.raises(RuntimeError, match="KAFKA_BOOTSTRAP_SERVERS"):
        with TestClient(app):
            pass
