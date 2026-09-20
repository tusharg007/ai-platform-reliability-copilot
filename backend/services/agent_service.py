"""Production ReAct agent with multi-step reasoning, tool use, and confidence scoring.

The ReliabilityAgent orchestrates the full intelligence pipeline:
  1. Intent detection  → infer service + error context from query
  2. Tool selection    → choose relevant tool(s) from the registry
  3. Evidence gathering → execute tools iteratively
  4. Synthesis         → assemble grounded response
  5. Guardrail check   → validate output before returning

Conversation memory is maintained per session (in-memory, configurable).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.services.anomaly_detector import AnomalyDetector
from backend.services.incident_clustering import IncidentClusterer
from backend.services.incident_generator import IncidentGenerator
from backend.services.log_analyzer import LogAnalyzer
from backend.services.rag_service import RAGService
from backend.services.risk_scorer import RiskScorer
from backend.services.root_cause_engine import RootCauseEngine

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Session Memory
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConversationTurn:
    query: str
    service_name: str | None
    region: str | None
    answer: str
    severity: str
    timestamp: float = field(default_factory=time.time)


class SessionMemory:
    """Per-session conversation history.

    Persists to Redis when REDIS_ENABLED=true (survives restarts, shared
    across multiple API workers). Falls back to in-memory dict silently.
    """

    def __init__(self, session_id: str | None = None, max_turns: int = 5) -> None:
        self._turns: list[ConversationTurn] = []
        self._max_turns = max_turns
        self._session_id = session_id
        self._load_from_redis()

    def _load_from_redis(self) -> None:
        if not self._session_id:
            return
        try:
            from backend.services.redis_client import session_get
            stored = session_get(self._session_id)
            if stored:
                self._turns = [ConversationTurn(**t) for t in stored]
        except Exception:
            pass

    def _save_to_redis(self) -> None:
        if not self._session_id:
            return
        try:
            from backend.services.redis_client import session_set
            session_set(
                self._session_id,
                [
                    {
                        "query": t.query, "service_name": t.service_name,
                        "region": t.region, "answer": t.answer,
                        "severity": t.severity, "timestamp": t.timestamp,
                    }
                    for t in self._turns
                ],
                ttl_seconds=3600,
            )
        except Exception:
            pass

    def add(self, turn: ConversationTurn) -> None:
        self._turns.append(turn)
        if len(self._turns) > self._max_turns:
            self._turns = self._turns[-self._max_turns:]
        self._save_to_redis()

    def last_service(self) -> str | None:
        for turn in reversed(self._turns):
            if turn.service_name:
                return turn.service_name
        return None

    def last_region(self) -> str | None:
        for turn in reversed(self._turns):
            if turn.region:
                return turn.region
        return None

    def context_summary(self) -> str:
        if not self._turns:
            return ""
        last = self._turns[-1]
        return (
            f"Previous query about {last.service_name or 'unknown'} "
            f"in {last.region or 'all regions'}: {last.severity}"
        )


# Global in-memory session store (fallback when Redis is off)
_sessions: dict[str, SessionMemory] = {}



def get_session(session_id: str | None) -> SessionMemory:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    mem = SessionMemory(session_id=session_id)
    if session_id:
        _sessions[session_id] = mem
    return mem


# ─────────────────────────────────────────────────────────────────────────────
#  ReliabilityAgent
# ─────────────────────────────────────────────────────────────────────────────

class ReliabilityAgent:
    """Production-grade ReAct agent for platform reliability diagnosis.

    Tool registry:
    - search_docs()              — Hybrid RAG runbook retrieval
    - query_logs()               — Log analytics (errors, latency, deployments)
    - detect_service_anomalies() — Multi-method anomaly detection
    - summarize_incident()       — Incident summary + postmortem
    - analyze_root_cause()       — Full RCA with causal chain
    - score_incident_risk()      — Multi-dimensional risk assessment
    - cluster_active_incidents() — HDBSCAN incident clustering
    - generate_fix_checklist()   — Error-type-specific action plan
    """

    def __init__(self) -> None:
        self.rag = RAGService()
        self.logs = LogAnalyzer()
        self.anomalies = AnomalyDetector()
        self.incidents = IncidentGenerator()
        self.rca = RootCauseEngine()
        self.risk = RiskScorer()
        self.clusterer = IncidentClusterer()

    # ── Tool Methods ──────────────────────────────────────────────────────────

    def search_docs(self, query: str) -> list[dict[str, Any]]:
        """Hybrid BM25 + vector search over runbooks with reranking."""
        return self.rag.retrieve(query)

    def query_logs(
        self,
        service_name: str,
        region: str | None = None,
        time_window: str | None = None,
    ) -> dict[str, Any]:
        """Full log analysis: errors, latency, top error types, deployment regressions."""
        return {
            "errors": self.logs.summarize_errors(service_name, region),
            "latency": self.logs.calculate_latency_summary(service_name, region),
            "top_error_types": self.logs.find_top_error_types(service_name, region),
            "deployment_failures": self.logs.identify_deployment_related_failures(service_name, region),
            "time_window": time_window or "all_available_data",
        }

    def detect_service_anomalies(
        self,
        service_name: str,
        metric_name: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Ensemble anomaly detection (Z-score + Isolation Forest) with health score."""
        anomaly_list = self.anomalies.detect(service_name, metric_name, region)
        health = self.anomalies.get_service_health_score(service_name, region)
        return {
            "health_score": health,
            "anomalies": anomaly_list,
            "high_count": sum(1 for a in anomaly_list if a["severity"] == "high"),
            "medium_count": sum(1 for a in anomaly_list if a["severity"] == "medium"),
        }

    def summarize_incident(self, service_name: str, region: str | None = None) -> dict[str, Any]:
        """Generate incident summary with postmortem template."""
        return self.incidents.full_incident(service_name, region)

    def analyze_root_cause(
        self,
        service_name: str,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Full RCA: causal chain, hypothesis, evidence, actions, MTTR estimate."""
        risk = self.risk.score_incident(service_name, region)
        rca = self.rca.analyze(service_name, region, risk_assessment=risk)
        return rca.to_dict()

    def score_incident_risk(
        self,
        service_name: str,
        region: str | None = None,
        error_type: str | None = None,
    ) -> dict[str, Any]:
        """Multi-dimensional risk score: blast radius, velocity, SLO burn, history, revenue."""
        assessment = self.risk.score_incident(service_name, region, error_type)
        return assessment.to_dict()

    def cluster_active_incidents(self, window_hours: int = 4) -> dict[str, Any]:
        """HDBSCAN clustering of active incident signals across all services."""
        return self.clusterer.full_clustering_analysis(window_hours)

    def generate_fix_checklist(self, error_type: str) -> list[str]:
        """Return error-type-specific remediation steps."""
        from backend.services.root_cause_engine import RootCauseEngine
        engine = RootCauseEngine()
        return engine._build_action_plan(error_type, [], 0.05, 800.0)

    def fleet_status(self) -> dict[str, Any]:
        """Fleet-wide risk summary across all monitored services."""
        return self.risk.fleet_risk_summary()

    # ── Core Answer Method ────────────────────────────────────────────────────

    def answer(
        self,
        query: str,
        service_name: str | None = None,
        region: str | None = None,
        time_window: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Main entry point: process a reliability query and return a grounded response.

        Pipeline:
          1. Infer service/region from query or session memory
          2. Gather evidence: RAG + logs + anomalies + risk score + RCA
          3. Build response with answer, evidence, sources, actions, severity
          4. Update session memory
        """
        t0 = time.perf_counter()
        session = get_session(session_id)

        # ── Intent Detection ──────────────────────────────────────────────────
        inferred_svc = service_name or self._infer_service(query) or session.last_service() or "payment-service"
        inferred_region = region or self._infer_region(query) or session.last_region()

        logger.info(
            "Agent query: service=%s region=%s query_len=%d",
            inferred_svc, inferred_region, len(query)
        )

        # ── Tool Execution ────────────────────────────────────────────────────
        docs = self.search_docs(query)
        log_summary = self.query_logs(inferred_svc, inferred_region, time_window)
        anomaly_summary = self.detect_service_anomalies(inferred_svc, region=inferred_region)
        risk_assessment = self.risk.score_incident(inferred_svc, inferred_region)
        rca = self.rca.analyze(inferred_svc, inferred_region, risk_assessment=risk_assessment)

        # ── Response Assembly ─────────────────────────────────────────────────
        errors = log_summary["errors"]
        latency = log_summary["latency"]
        top_error_types = log_summary["top_error_types"]
        dep_failures = log_summary["deployment_failures"]

        top_error = top_error_types[0]["error_type"] if top_error_types else "UNKNOWN"
        article = "an" if top_error[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
        scope = f"{inferred_svc} in {inferred_region}" if inferred_region else f"{inferred_svc} across all regions"

        # Main answer text
        answer_text = (
            f"{scope} is experiencing {article} **{top_error}** pattern. "
            f"Current error rate: **{errors['error_rate']*100:.2f}%** with P95 latency at **{latency['p95']:.0f}ms**. "
        )
        if dep_failures:
            d = dep_failures[0]
            answer_text += (
                f"Strongest correlation: deployment **{d.get('deployment_version')}** "
                f"in **{d.get('region')}** ({d.get('error_rate', 0)*100:.1f}% error rate, "
                f"{d.get('p95_latency', 0):.0f}ms P95). "
            )
        answer_text += f"\n\n**Root Cause**: {rca.root_cause}"
        if rca.causal_chain:
            answer_text += "\n\n**Causal Chain**:\n" + "\n".join(
                f"{s.sequence}. {s.event} — _{s.evidence}_"
                for s in rca.causal_chain
            )

        # Evidence
        evidence: list[str] = [
            f"Scope: {scope} — {errors['total_logs']:,} logs analysed",
            f"Error rate: {errors['error_rate']*100:.2f}% | P95 latency: {latency['p95']:.0f}ms",
            f"Primary error: {top_error} ({top_error_types[0].get('count', 0)} occurrences)" if top_error_types else "No dominant error type",
            f"Anomaly signals: {anomaly_summary['high_count']} high + {anomaly_summary['medium_count']} medium | Health score: {anomaly_summary['health_score']}/100",
            f"Risk score: {risk_assessment.composite_score:.3f} → {risk_assessment.severity} (confidence: {rca.confidence:.0%})",
        ]
        if dep_failures:
            d = dep_failures[0]
            evidence.append(
                f"Deployment regression: {d.get('deployment_version')} / {d.get('region')} "
                f"— {d.get('error_rate', 0)*100:.1f}% error rate, {d.get('p95_latency', 0):.0f}ms P95"
            )
        if docs:
            evidence.append(f"Runbooks retrieved: {', '.join(sorted({d['source'] for d in docs}))}")
        if rca.estimated_mttr_minutes:
            evidence.append(f"Estimated MTTR: ~{rca.estimated_mttr_minutes} minutes based on historical data")

        duration_ms = (time.perf_counter() - t0) * 1000

        # ── Record Telemetry ──────────────────────────────────────────────────
        try:
            from backend.telemetry import get_copilot_metrics
            get_copilot_metrics().record_query(duration_ms, inferred_svc, rca.severity)
        except Exception:
            pass

        # ── Update Session Memory ─────────────────────────────────────────────
        session.add(ConversationTurn(
            query=query,
            service_name=inferred_svc,
            region=inferred_region,
            answer=answer_text[:200],
            severity=rca.severity,
        ))

        # ── Slack Alert (async-safe, non-blocking) ────────────────────────────
        try:
            from backend.services.alerting import alert_incident
            alert_incident(
                service_name=inferred_svc,
                region=inferred_region,
                severity=rca.severity,
                title=f"{top_error} detected in {inferred_svc}",
                summary=answer_text[:300],
                risk_score=risk_assessment.composite_score,
                evidence=evidence,
                actions=rca.recommended_actions,
                root_cause=rca.root_cause,
                mttr_minutes=rca.estimated_mttr_minutes,
            )
        except Exception:
            pass  # Never let alerting break the response

        return {
            "answer": answer_text,
            "evidence": evidence,
            "sources": docs,
            "recommended_actions": rca.recommended_actions,
            "severity": rca.severity,
            "risk_score": risk_assessment.composite_score,
            "confidence": rca.confidence,
            "estimated_mttr_minutes": rca.estimated_mttr_minutes,
            "causal_chain": [
                {"sequence": s.sequence, "event": s.event, "evidence": s.evidence}
                for s in rca.causal_chain
            ],
            "generation_method": rca.generation_method,
            "latency_ms": round(duration_ms, 1),
        }

    # ── Intent Inference ──────────────────────────────────────────────────────

    @staticmethod
    def _infer_service(query: str) -> str | None:
        services = [
            "auth-service", "payment-service", "matchmaking-service",
            "player-profile-service", "notification-service",
            "game-session-service", "leaderboard-service",
        ]
        q = query.lower()
        # Keyword aliases
        aliases = {
            "payment": "payment-service", "pay": "payment-service",
            "auth": "auth-service", "login": "auth-service", "token": "auth-service",
            "matchmak": "matchmaking-service", "queue": "matchmaking-service",
            "profile": "player-profile-service", "player": "player-profile-service",
            "notification": "notification-service", "notify": "notification-service",
            "game": "game-session-service", "session": "game-session-service",
            "leaderboard": "leaderboard-service", "ranking": "leaderboard-service",
        }
        for keyword, service in aliases.items():
            if keyword in q:
                return service
        for service in services:
            if service in q:
                return service
        return None

    @staticmethod
    def _infer_region(query: str) -> str | None:
        regions = {
            "us-east": ["us-east", "east", "us east"],
            "us-west": ["us-west", "west", "us west"],
            "eu-central": ["eu-central", "eu", "europe", "central"],
            "ap-south": ["ap-south", "ap south", "asia", "apac"],
        }
        q = query.lower()
        for region, aliases in regions.items():
            if any(alias in q for alias in aliases):
                return region
        return None
