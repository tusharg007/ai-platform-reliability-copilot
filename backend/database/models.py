"""SQLAlchemy 2.0 ORM models for the AI Platform Reliability Copilot.

All tables are designed to work with both SQLite (development) and
PostgreSQL (production).  When using PostgreSQL, enable the pgvector
extension for embedding columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
#  Core Telemetry Tables
# ─────────────────────────────────────────────────────────────────────────────

class LogEntry(Base):
    """Structured log event from an observed microservice.

    Maps directly to the ``logs`` table loaded from synthetic_logs.csv.
    In production, rows are streamed from Kafka / OTel Collector.
    """

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False, default="production")
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    deployment_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_logs_svc_region_ts", "service_name", "region", "timestamp"),
        Index("ix_logs_status_code", "status_code"),
        Index("ix_logs_error_type", "error_type"),
    )

    def __repr__(self) -> str:
        return f"<LogEntry {self.service_name}/{self.region} {self.status_code} @ {self.timestamp}>"


class MetricDatapoint(Base):
    """Aggregated metrics sample for a service/region over a time window.

    Maps to the ``metrics`` table populated from service_metrics.csv.
    In production, aggregated from Prometheus scrapes via stream processor.
    """

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    cpu_usage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    memory_usage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p95_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deployment_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_metrics_svc_region_ts", "service_name", "region", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<MetricDatapoint {self.service_name}/{self.region} err={self.error_rate:.3f} @ {self.timestamp}>"


# ─────────────────────────────────────────────────────────────────────────────
#  Incident Management Tables
# ─────────────────────────────────────────────────────────────────────────────

class IncidentCluster(Base):
    """A group of related incident signals identified by HDBSCAN clustering.

    Clusters are created automatically when ≥2 incidents share similar
    embedding vectors (same error pattern, overlapping services/regions).
    """

    __tablename__ = "incident_clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    centroid_service: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    centroid_error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    blast_radius: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    velocity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="SEV-4")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
    incidents: Mapped[list["Incident"]] = relationship("Incident", back_populates="cluster")

    def __repr__(self) -> str:
        return f"<IncidentCluster {self.name} sev={self.severity} risk={self.risk_score:.2f}>"


class Incident(Base):
    """An individual reliability incident, optionally grouped into a cluster.

    Incidents are either loaded from incidents.csv (historical) or created
    automatically by the AnomalyDetector when thresholds are breached.
    """

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("incident_clusters.id"), nullable=True
    )
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    environment: Mapped[str] = mapped_column(String(64), nullable=False, default="production")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="SEV-4")
    issue_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    deployment_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
    cluster: Mapped[Optional["IncidentCluster"]] = relationship("IncidentCluster", back_populates="incidents")
    risk_scores: Mapped[list["RiskScore"]] = relationship("RiskScore", back_populates="incident")
    runbook_retrievals: Mapped[list["RunbookRetrieval"]] = relationship(
        "RunbookRetrieval", back_populates="incident"
    )

    __table_args__ = (
        Index("ix_incidents_svc_sev_status", "service_name", "severity", "status"),
    )

    def __repr__(self) -> str:
        return f"<Incident {self.incident_id or self.id} {self.service_name} {self.severity}>"


# ─────────────────────────────────────────────────────────────────────────────
#  Risk Scoring Table
# ─────────────────────────────────────────────────────────────────────────────

class RiskScore(Base):
    """Detailed multi-dimensional risk assessment for an incident or cluster.

    Stores individual dimension scores alongside the composite weighted score
    so that engineers can audit *why* a particular risk level was assigned.
    """

    __tablename__ = "risk_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=True
    )
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("incident_clusters.id"), nullable=True
    )
    blast_radius_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    velocity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slo_burn_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    historical_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    revenue_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="SEV-4")
    contributing_factors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # Relationships
    incident: Mapped[Optional["Incident"]] = relationship("Incident", back_populates="risk_scores")

    def __repr__(self) -> str:
        return f"<RiskScore {self.severity} composite={self.composite_score:.3f}>"


# ─────────────────────────────────────────────────────────────────────────────
#  RAG / Runbook Retrieval Table
# ─────────────────────────────────────────────────────────────────────────────

class RunbookRetrieval(Base):
    """Records each RAG retrieval event for quality monitoring and audit.

    Enables offline analysis of retrieval precision, MRR, and latency trends.
    """

    __tablename__ = "runbook_retrievals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(String(256), nullable=False)
    chunk_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_method: Mapped[str] = mapped_column(String(32), nullable=False, default="bm25")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # Relationships
    incident: Mapped[Optional["Incident"]] = relationship("Incident", back_populates="runbook_retrievals")

    def __repr__(self) -> str:
        return f"<RunbookRetrieval {self.source_file} score={self.relevance_score:.3f}>"


# ─────────────────────────────────────────────────────────────────────────────
#  Eval & Feedback Tables
# ─────────────────────────────────────────────────────────────────────────────

class EvalResult(Base):
    """Result of running a single evaluation case against the copilot.

    Populated by the ``evals/runner.py`` evaluation framework and used
    to track quality over time / catch regressions in CI.
    """

    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    groundedness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hallucination_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_precision: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eval_dataset: Mapped[str] = mapped_column(String(128), nullable=False, default="golden_set")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    def __repr__(self) -> str:
        return f"<EvalResult passed={self.passed} groundedness={self.groundedness_score:.2f}>"


class UserFeedback(Base):
    """User-submitted feedback on a copilot response.

    Used for RLHF-style quality analysis and to populate the regression
    eval dataset when users flag incorrect answers.
    """

    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–5
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    service_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    def __repr__(self) -> str:
        return f"<UserFeedback rating={self.rating}/5 svc={self.service_name}>"
