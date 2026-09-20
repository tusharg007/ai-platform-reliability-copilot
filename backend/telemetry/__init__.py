"""OpenTelemetry self-instrumentation — PRODUCTION GRADE, actually works.

Three export paths (all can run simultaneously):
  1. Prometheus  — always on when OTEL_ENABLED=true. Exposes /metrics endpoint
                   that Prometheus scrapes directly. No external collector needed.
  2. OTLP/gRPC   — optional. Set OTEL_EXPORTER_OTLP_ENDPOINT to enable.
                   Sends to OTel Collector → Jaeger / Tempo for traces.
  3. Console      — set OTEL_CONSOLE_EXPORT=true for local debug.

Default behaviour (what you get with OTEL_ENABLED=true):
  - Prometheus metrics at GET /metrics
  - FastAPI auto-instrumentation (every HTTP request traced)
  - 7 custom business metrics: query.duration, anomaly.detected, etc.
  - Structured JSON logging via structlog
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

import structlog

from backend.utils.config import get_settings

# ─────────────────────────────────────────────────────────────────────────────
#  Structured Logging Setup
# ─────────────────────────────────────────────────────────────────────────────

def configure_logging() -> None:
    """Configure structlog: JSON in production, coloured console in local dev."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)


def get_logger(name: str = __name__) -> Any:
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)


# ─────────────────────────────────────────────────────────────────────────────
#  OpenTelemetry Setup
# ─────────────────────────────────────────────────────────────────────────────

_tracer = None
_meter = None
_prometheus_registry = None   # exposed via /metrics
_otel_initialized = False


def setup_otel(app: Any = None) -> None:
    """Initialise OpenTelemetry with Prometheus + optional OTLP export.

    Prometheus exporter is ALWAYS enabled when OTEL_ENABLED=true — it
    exposes /metrics for Prometheus to scrape, requiring zero external
    infrastructure.

    OTLP is enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set.
    """
    global _tracer, _meter, _prometheus_registry, _otel_initialized

    settings = get_settings()
    if not settings.otel_enabled:
        return

    try:
        from opentelemetry import metrics as otel_metrics
        from opentelemetry import trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        resource = Resource.create({
            "service.name": settings.otel_service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.environment,
        })

        # ── Metric Readers: Prometheus (always) + optional OTLP ──────────────
        readers = []

        # 1. Prometheus exporter — scrape at GET /metrics
        try:
            from opentelemetry.exporter.prometheus import PrometheusMetricReader
            prom_reader = PrometheusMetricReader()
            readers.append(prom_reader)
            _prometheus_registry = True
            get_logger(__name__).info("Prometheus metrics exporter enabled → GET /metrics")
        except ImportError:
            get_logger(__name__).warning("opentelemetry-exporter-prometheus not installed; /metrics disabled")

        # 2. OTLP exporter — only if endpoint is configured
        otlp_endpoint = settings.otel_exporter_endpoint
        if otlp_endpoint and otlp_endpoint not in ("", "disabled"):
            try:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )
                otlp_metric_reader = PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=otlp_endpoint),
                    export_interval_millis=30_000,
                )
                readers.append(otlp_metric_reader)
                get_logger(__name__).info("OTLP metrics exporter enabled", endpoint=otlp_endpoint)
            except Exception as exc:
                get_logger(__name__).warning("OTLP metric exporter failed", error=str(exc))

        # 3. Console exporter for local debug
        if getattr(settings, "otel_console_export", False):
            console_reader = PeriodicExportingMetricReader(
                ConsoleMetricExporter(), export_interval_millis=60_000
            )
            readers.append(console_reader)

        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        otel_metrics.set_meter_provider(meter_provider)
        _meter = otel_metrics.get_meter(settings.otel_service_name)

        # ── Tracer: Console (always) + optional OTLP ─────────────────────────
        tracer_provider = TracerProvider(resource=resource)

        if otlp_endpoint and otlp_endpoint not in ("", "disabled"):
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
                )
                get_logger(__name__).info("OTLP trace exporter enabled", endpoint=otlp_endpoint)
            except Exception as exc:
                get_logger(__name__).warning("OTLP trace exporter failed", error=str(exc))
        else:
            # Use console exporter so traces are visible even without a collector
            tracer_provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )

        trace.set_tracer_provider(tracer_provider)
        _tracer = trace.get_tracer(settings.otel_service_name)

        # ── FastAPI Auto-Instrumentation ──────────────────────────────────────
        if app is not None:
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
                FastAPIInstrumentor.instrument_app(
                    app,
                    excluded_urls="/health,/metrics,/pipeline/status",
                )
                get_logger(__name__).info("FastAPI auto-instrumentation enabled")
            except ImportError:
                pass

        _otel_initialized = True
        get_logger(__name__).info(
            "OpenTelemetry initialised",
            prometheus_enabled=_prometheus_registry is not None,
            otlp_enabled=bool(otlp_endpoint),
        )

    except ImportError as exc:
        get_logger(__name__).warning("OTel SDK not installed; skipping", error=str(exc))
    except Exception as exc:
        get_logger(__name__).warning("OTel setup failed", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Prometheus /metrics endpoint helper
# ─────────────────────────────────────────────────────────────────────────────

def get_prometheus_metrics_response():
    """Return raw Prometheus text-format metrics for the /metrics endpoint.

    Returns (content, media_type) tuple. Returns None if Prometheus exporter
    is not initialised.
    """
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    except ImportError:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
#  Tracer / Meter accessors
# ─────────────────────────────────────────────────────────────────────────────

def get_tracer():
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        return trace.get_tracer("reliability-copilot")
    except ImportError:
        return _NoOpTracer()


def get_meter():
    if _meter is not None:
        return _meter
    return _NoOpMeter()


# ─────────────────────────────────────────────────────────────────────────────
#  Business Metrics
# ─────────────────────────────────────────────────────────────────────────────

class CopilotMetrics:
    """Typed wrapper around OTel instruments for business-level KPIs.

    All metrics are also exposed at /metrics for Prometheus scraping.
    """

    def __init__(self) -> None:
        meter = get_meter()
        self.query_duration = meter.create_histogram(
            "copilot_query_duration_ms",
            unit="ms",
            description="End-to-end latency of copilot answer() calls",
        )
        self.anomaly_detected = meter.create_counter(
            "copilot_anomaly_detected_total",
            description="Number of anomalies detected per service/metric",
        )
        self.risk_score = meter.create_histogram(
            "copilot_risk_score",
            description="Composite risk score per incident (0.0–1.0)",
        )
        self.rag_retrieval_latency = meter.create_histogram(
            "copilot_rag_retrieval_duration_ms",
            unit="ms",
            description="RAG retrieval latency (BM25 + dense + RRF)",
        )
        self.llm_call_duration = meter.create_histogram(
            "copilot_llm_call_duration_ms",
            unit="ms",
            description="LLM inference latency per provider",
        )
        self.slack_alerts_sent = meter.create_counter(
            "copilot_slack_alerts_total",
            description="Slack alerts sent by severity",
        )
        self.ingestion_events = meter.create_counter(
            "copilot_ingestion_events_total",
            description="Events processed by the streaming ingestion pipeline",
        )
        self.active_incidents = meter.create_up_down_counter(
            "copilot_active_incidents",
            description="Currently active incidents tracked in the system",
        )

    def record_query(self, duration_ms: float, severity: str, provider: str) -> None:
        self.query_duration.record(
            duration_ms, {"severity": severity, "provider": provider}
        )

    def record_anomaly(self, service: str, metric: str, severity: str) -> None:
        self.anomaly_detected.add(
            1, {"service": service, "metric": metric, "severity": severity}
        )

    def record_risk(self, score: float, service: str, sev: str) -> None:
        self.risk_score.record(score, {"service": service, "severity": sev})

    def record_rag(self, duration_ms: float, method: str) -> None:
        self.rag_retrieval_latency.record(duration_ms, {"method": method})

    def record_llm(self, duration_ms: float, provider: str, model: str) -> None:
        self.llm_call_duration.record(
            duration_ms, {"provider": provider, "model": model}
        )

    def record_slack(self, severity: str) -> None:
        self.slack_alerts_sent.add(1, {"severity": severity})

    def record_ingestion(self, event_type: str) -> None:
        self.ingestion_events.add(1, {"type": event_type})


_copilot_metrics: CopilotMetrics | None = None


def get_copilot_metrics() -> CopilotMetrics:
    """Return the singleton CopilotMetrics instance."""
    global _copilot_metrics
    if _copilot_metrics is None:
        _copilot_metrics = CopilotMetrics()
    return _copilot_metrics


# ─────────────────────────────────────────────────────────────────────────────
#  No-Op Fallbacks (when OTel is disabled)
# ─────────────────────────────────────────────────────────────────────────────

class _NoOpTracer:
    def start_as_current_span(self, name: str, **kwargs):
        from contextlib import contextmanager
        @contextmanager
        def _noop():
            yield _NoOpSpan()
        return _noop()

class _NoOpSpan:
    def set_attribute(self, *a, **kw): pass
    def record_exception(self, *a, **kw): pass

class _NoOpMeter:
    def create_histogram(self, *a, **kw): return _NoOpInstrument()
    def create_counter(self, *a, **kw): return _NoOpInstrument()
    def create_up_down_counter(self, *a, **kw): return _NoOpInstrument()
    def create_gauge(self, *a, **kw): return _NoOpInstrument()

class _NoOpInstrument:
    def record(self, *a, **kw): pass
    def add(self, *a, **kw): pass
    def observe(self, *a, **kw): pass
