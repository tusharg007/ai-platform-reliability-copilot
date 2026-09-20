"""LLM-powered root-cause analysis engine with causal chain reasoning.

The RootCauseEngine synthesises evidence from multiple sources into
a structured root-cause analysis with:
  - Causal chain (ordered sequence of events)
  - Root cause hypothesis with confidence score
  - Supporting evidence (grounded in telemetry)
  - Prioritised recommended actions
  - Runbook references with section citations
  - Estimated MTTR from historical data

All outputs are validated by the guardrail layer before being returned.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from backend.services.anomaly_detector import AnomalyDetector
from backend.services.incident_clustering import IncidentCluster
from backend.services.log_analyzer import LogAnalyzer
from backend.services.rag_service import RAGService
from backend.services.risk_scorer import RiskAssessment
from backend.utils.config import get_settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CausalStep:
    """One step in a causal chain leading to the incident."""
    sequence: int
    event: str
    evidence: str
    timestamp_hint: str = ""


@dataclass
class RootCauseAnalysis:
    """Complete structured root-cause analysis output."""
    service_name: str
    region: str | None
    causal_chain: list[CausalStep] = field(default_factory=list)
    root_cause: str = ""
    confidence: float = 0.0        # 0.0–1.0
    evidence: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    runbook_references: list[str] = field(default_factory=list)
    estimated_mttr_minutes: int = 0
    severity: str = "SEV-4"
    risk_score: float = 0.0
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    generation_method: str = "deterministic"  # "llm" | "deterministic"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["causal_chain"] = [asdict(s) for s in self.causal_chain]
        return d


# ─────────────────────────────────────────────────────────────────────────────
#  RCA Context Builder
# ─────────────────────────────────────────────────────────────────────────────

class RCAContextBuilder:
    """Gathers and structures evidence for root-cause analysis."""

    def __init__(self) -> None:
        self._log_analyzer = LogAnalyzer()
        self._anomaly_detector = AnomalyDetector()
        self._rag = RAGService()

    def build(
        self,
        service_name: str,
        region: str | None = None,
        cluster: IncidentCluster | None = None,
        risk_assessment: RiskAssessment | None = None,
    ) -> dict[str, Any]:
        """Gather all evidence needed for root-cause reasoning."""
        # Log analytics
        errors = self._log_analyzer.summarize_errors(service_name, region)
        latency = self._log_analyzer.calculate_latency_summary(service_name, region)
        top_errors = self._log_analyzer.find_top_error_types(service_name, region)
        dep_failures = self._log_analyzer.identify_deployment_related_failures(service_name, region)

        # Anomaly detection
        anomalies = self._anomaly_detector.detect(service_name, region=region)
        health_score = self._anomaly_detector.get_service_health_score(service_name, region)

        # RAG runbook retrieval
        top_error = top_errors[0]["error_type"] if top_errors else "unknown"
        rag_query = f"{service_name} {top_error} {region or ''} troubleshooting"
        runbook_chunks = self._rag.retrieve(rag_query, top_k=4)

        return {
            "service_name": service_name,
            "region": region,
            "errors": errors,
            "latency": latency,
            "top_error_types": top_errors,
            "deployment_failures": dep_failures,
            "anomalies": anomalies,
            "health_score": health_score,
            "runbook_chunks": runbook_chunks,
            "cluster": cluster,
            "risk_assessment": risk_assessment,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Root Cause Engine
# ─────────────────────────────────────────────────────────────────────────────

class RootCauseEngine:
    """Generates grounded root-cause recommendations using structured reasoning.

    When an LLM is configured, uses it for richer causal chain synthesis.
    Always falls back to a deterministic, evidence-grounded analysis.
    """

    # Historical MTTR estimates by error type
    _MTTR_ESTIMATES: dict[str, int] = {
        "DB_CONNECTION_TIMEOUT": 75,
        "AUTH_TOKEN_EXPIRED":    30,
        "UPSTREAM_503":          45,
        "CACHE_MISS_STORM":      20,
        "RATE_LIMIT_EXCEEDED":   15,
        "MATCHMAKING_QUEUE_TIMEOUT": 35,
        "UNKNOWN":               60,
    }

    def __init__(self) -> None:
        self._context_builder = RCAContextBuilder()

    def analyze(
        self,
        service_name: str,
        region: str | None = None,
        cluster: IncidentCluster | None = None,
        risk_assessment: RiskAssessment | None = None,
    ) -> RootCauseAnalysis:
        """Run full root-cause analysis and return a structured RCA.

        Args:
            service_name:     Affected microservice.
            region:           Affected cloud region (None = all).
            cluster:          Optional incident cluster context.
            risk_assessment:  Optional pre-computed risk assessment.

        Returns:
            A :class:`RootCauseAnalysis` with causal chain, root cause,
            evidence, recommended actions, and MTTR estimate.
        """
        context = self._context_builder.build(service_name, region, cluster, risk_assessment)

        # Try LLM analysis first
        llm_rca = self._try_llm_analysis(context)
        if llm_rca:
            return llm_rca

        # Deterministic analysis
        return self._deterministic_analysis(context)

    # ── Deterministic Analysis ────────────────────────────────────────────────

    def _deterministic_analysis(self, ctx: dict[str, Any]) -> RootCauseAnalysis:
        """Build a grounded RCA from telemetry data without an LLM."""
        service_name = ctx["service_name"]
        region = ctx["region"]
        errors = ctx["errors"]
        latency = ctx["latency"]
        top_errors = ctx["top_error_types"]
        dep_failures = ctx["deployment_failures"]
        anomalies = ctx["anomalies"]
        health_score = ctx["health_score"]
        runbook_chunks = ctx["runbook_chunks"]
        risk_assessment: RiskAssessment | None = ctx.get("risk_assessment")

        top_error_type = top_errors[0]["error_type"] if top_errors else "UNKNOWN"
        error_rate = errors["error_rate"]
        p95 = latency["p95"]

        # ── Causal Chain Construction ──────────────────────────────────────────
        causal_chain: list[CausalStep] = []
        step = 1

        if dep_failures:
            worst = dep_failures[0]
            causal_chain.append(CausalStep(
                sequence=step,
                event=f"Deployment {worst.get('deployment_version')} rolled out to {worst.get('region')}",
                evidence=f"Deployment version change detected; error rate jumped to "
                         f"{worst.get('error_rate', 0)*100:.1f}% in {worst.get('region')}",
            ))
            step += 1

        high_anomalies = [a for a in anomalies if a["severity"] == "high"]
        if high_anomalies:
            for a in high_anomalies[:2]:
                causal_chain.append(CausalStep(
                    sequence=step,
                    event=f"{a['metric_name']} spiked to {a['observed_value']} (baseline: {a['baseline_value']})",
                    evidence=f"Z-score anomaly detected at {a['anomaly_timestamp']} in {a.get('region')}",
                ))
                step += 1

        causal_chain.append(CausalStep(
            sequence=step,
            event=f"Service begins returning {top_error_type} errors",
            evidence=f"Error rate reached {error_rate*100:.2f}%; P95 latency at {p95:.0f}ms",
        ))
        step += 1

        causal_chain.append(CausalStep(
            sequence=step,
            event=f"Health score degraded to {health_score}/100",
            evidence=f"{len(anomalies)} metric anomalies detected across latency, error rate, and saturation",
        ))

        # ── Root Cause Hypothesis ──────────────────────────────────────────────
        if dep_failures and top_error_type == "DB_CONNECTION_TIMEOUT":
            root_cause = (
                f"Deployment {dep_failures[0].get('deployment_version')} introduced a database "
                f"connection pool regression in {service_name} ({region or 'all regions'}). "
                f"The new version increased connection demand beyond the pool limit, causing "
                f"timeouts to cascade at {error_rate*100:.1f}% error rate."
            )
            confidence = 0.88
        elif dep_failures:
            root_cause = (
                f"Deployment regression in {dep_failures[0].get('deployment_version')} caused "
                f"{top_error_type} errors in {service_name}. The deployment correlates with "
                f"error rate spike from baseline to {error_rate*100:.1f}%."
            )
            confidence = 0.75
        elif top_error_type == "CACHE_MISS_STORM":
            root_cause = (
                f"Cache invalidation storm in {service_name}: high cache miss rate is causing "
                f"all requests to fall through to the database, amplifying latency to {p95:.0f}ms P95."
            )
            confidence = 0.70
        elif top_error_type == "AUTH_TOKEN_EXPIRED":
            root_cause = (
                f"Authentication token expiry cascade: signing keys or token refresh mechanism "
                f"in {service_name} is failing, causing authentication failures at {error_rate*100:.1f}%."
            )
            confidence = 0.72
        else:
            root_cause = (
                f"{service_name} is experiencing {top_error_type} errors at {error_rate*100:.1f}% "
                f"error rate with P95 latency of {p95:.0f}ms. The primary signal suggests upstream "
                f"dependency degradation or resource saturation."
            )
            confidence = 0.55

        # ── Evidence Collection ────────────────────────────────────────────────
        evidence: list[str] = [
            f"Scope: {service_name} in {region or 'all regions'} — {errors['total_logs']} logs analysed",
            f"Error rate: {error_rate*100:.2f}% (threshold 5%)",
            f"P95 latency: {p95:.0f}ms (threshold 500ms)",
            f"Primary error signature: {top_error_type} ({top_errors[0].get('count', 0)} occurrences)" if top_errors else "No dominant error type",
            f"Anomaly count: {len(anomalies)} signals detected; health score {health_score}/100",
        ]
        if dep_failures:
            evidence.append(
                f"Deployment correlation: version {dep_failures[0].get('deployment_version')} "
                f"in {dep_failures[0].get('region')} — {dep_failures[0].get('error_rate', 0)*100:.1f}% error rate"
            )
        if risk_assessment:
            evidence.append(
                f"Risk score: {risk_assessment.composite_score:.3f} → {risk_assessment.severity} "
                f"(blast_radius={risk_assessment.blast_radius_score:.2f}, "
                f"slo_burn={risk_assessment.slo_burn_score:.2f})"
            )

        # ── Recommended Actions ────────────────────────────────────────────────
        actions = self._build_action_plan(top_error_type, dep_failures, error_rate, p95)

        # ── Runbook References ─────────────────────────────────────────────────
        runbook_refs = list({c["source"] for c in runbook_chunks})

        # ── MTTR Estimate ──────────────────────────────────────────────────────
        mttr = self._MTTR_ESTIMATES.get(top_error_type, 60)

        # ── Severity ──────────────────────────────────────────────────────────
        if error_rate >= 0.10 or p95 >= 1200:
            severity = "SEV-1"
        elif error_rate >= 0.05 or p95 >= 800:
            severity = "SEV-2"
        elif error_rate >= 0.02 or p95 >= 500:
            severity = "SEV-3"
        else:
            severity = "SEV-4"

        if risk_assessment:
            severity = risk_assessment.severity  # Prefer scored severity

        return RootCauseAnalysis(
            service_name=service_name,
            region=region,
            causal_chain=causal_chain,
            root_cause=root_cause,
            confidence=confidence,
            evidence=evidence,
            recommended_actions=actions,
            runbook_references=runbook_refs,
            estimated_mttr_minutes=mttr,
            severity=severity,
            risk_score=risk_assessment.composite_score if risk_assessment else 0.0,
            generation_method="deterministic",
        )

    def _build_action_plan(
        self,
        error_type: str,
        dep_failures: list[dict],
        error_rate: float,
        p95: float,
    ) -> list[str]:
        """Build a prioritised, error-type-specific action checklist."""
        actions: list[str] = []

        # Universal first-response steps
        actions.append("📋 Open incident channel and assign incident commander (IC)")
        actions.append(f"📊 Confirm scope: check Grafana/metrics for affected services and regions")

        if dep_failures:
            ver = dep_failures[0].get("deployment_version", "unknown")
            actions.append(f"🔄 Evaluate rollback of deployment {ver} if error rate > 5% for > 10 min")

        if error_type == "DB_CONNECTION_TIMEOUT":
            actions.extend([
                "🔍 Check database connection pool utilisation (target: < 80%)",
                "⚡ Increase connection pool size as emergency mitigation (max_connections +50%)",
                "🔬 Verify no schema migration or lock is blocking connections",
                "🚫 Enable circuit breaker on DB calls to prevent retry storm",
                "📈 Monitor timeout_count metric — should drop within 5 min of fix",
            ])
        elif error_type == "AUTH_TOKEN_EXPIRED":
            actions.extend([
                "🔑 Refresh JWKS signing key cache immediately",
                "🔍 Check token refresh endpoint latency and error rate",
                "📊 Verify token expiry TTL settings match client refresh interval",
                "⚡ Rate-limit noisy clients causing token refresh storms",
            ])
        elif error_type == "CACHE_MISS_STORM":
            actions.extend([
                "🔥 Warm high-traffic cache keys proactively",
                "⚡ Apply backpressure on cache-miss path to protect DB",
                "📊 Check cache hit rate — target > 85%",
                "🔄 Restart cache warmer process if stuck",
            ])
        elif error_type == "MATCHMAKING_QUEUE_TIMEOUT":
            actions.extend([
                "📈 Scale matchmaking queue consumers horizontally",
                "🔧 Temporarily relax strict matching constraints (latency/skill)",
                "🌐 Redirect traffic away from constrained regions",
                "📊 Monitor queue depth — should stabilise within 10 min",
            ])
        elif error_type == "RATE_LIMIT_EXCEEDED":
            actions.extend([
                "🔍 Identify which clients are triggering rate limits (trace_id analysis)",
                "⚡ Apply temporary rate limit exemption for legitimate traffic",
                "📊 Review rate limit thresholds vs current traffic volume",
            ])
        else:
            actions.extend([
                "🔍 Review service logs for error patterns and upstream dependency status",
                "📊 Check upstream service health and latency",
                "⚡ Apply circuit breaker if upstream is degraded",
            ])

        # Universal escalation
        if error_rate >= 0.05:
            actions.append("🚨 Escalate to SEV-2 if error rate persists > 5% for 15 min (notify stakeholders)")
        actions.append("📝 Start incident postmortem document after mitigation")

        return actions

    # ── LLM Analysis ──────────────────────────────────────────────────────────

    def _try_llm_analysis(self, ctx: dict[str, Any]) -> RootCauseAnalysis | None:
        """Attempt LLM-powered root-cause analysis with structured output."""
        settings = get_settings()
        if settings.llm_provider == "mock":
            return None
        if not any([settings.openai_api_key, settings.groq_api_key, settings.gemini_api_key]):
            return None

        prompt = self._build_llm_prompt(ctx)
        response_text = self._call_llm(prompt, settings)
        if not response_text:
            return None

        return self._parse_llm_response(response_text, ctx)

    def _build_llm_prompt(self, ctx: dict[str, Any]) -> str:
        """Build a structured prompt for LLM root-cause analysis."""
        service = ctx["service_name"]
        region = ctx.get("region") or "all regions"
        errors = ctx["errors"]
        latency = ctx["latency"]
        top_errors = ctx["top_error_types"]
        dep_failures = ctx["deployment_failures"]
        anomalies = ctx["anomalies"]
        runbook_chunks = ctx["runbook_chunks"]

        runbook_context = "\n\n".join(
            f"[{c['source']}]\n{c['text']}" for c in runbook_chunks[:3]
        )

        return f"""You are a senior Site Reliability Engineer performing root-cause analysis.

TELEMETRY EVIDENCE:
- Service: {service} in {region}
- Error rate: {errors['error_rate']*100:.2f}%
- P95 latency: {latency['p95']:.0f}ms
- Top errors: {json.dumps(top_errors[:3], indent=2)}
- Deployment failures: {json.dumps(dep_failures[:2], indent=2)}
- Anomalies: {len(anomalies)} signals detected (high: {sum(1 for a in anomalies if a['severity']=='high')})

RUNBOOK CONTEXT:
{runbook_context}

INSTRUCTIONS:
1. Build a causal chain (max 5 steps) from the earliest observable signal to the user impact.
2. State the root cause hypothesis with a confidence score 0.0-1.0.
3. List 5-8 prioritised recommended actions referencing the runbooks.
4. Estimate MTTR in minutes based on similar past incidents.

IMPORTANT: Only use information from the telemetry evidence and runbook context above.
Do NOT invent metric values, service names, or runbook content that isn't provided.

Respond ONLY with valid JSON in this exact structure:
{{
  "causal_chain": [
    {{"sequence": 1, "event": "...", "evidence": "..."}}
  ],
  "root_cause": "...",
  "confidence": 0.85,
  "recommended_actions": ["...", "..."],
  "estimated_mttr_minutes": 45
}}"""

    def _call_llm(self, prompt: str, settings: Any) -> str | None:
        """Call the configured LLM provider."""
        system = "You are an expert SRE. Respond only with valid JSON."

        # Gemini
        if settings.llm_provider == "gemini" and settings.gemini_api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.gemini_api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                resp = model.generate_content(prompt)
                return resp.text
            except Exception as exc:
                logger.warning("Gemini RCA failed: %s", exc)

        # OpenAI
        if settings.llm_provider == "openai" and settings.openai_api_key:
            try:
                import openai
                client = openai.OpenAI(api_key=settings.openai_api_key)
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1200,
                    temperature=0.1,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                logger.warning("OpenAI RCA failed: %s", exc)

        # Groq
        if settings.llm_provider == "groq" and settings.groq_api_key:
            try:
                from groq import Groq
                client = Groq(api_key=settings.groq_api_key)
                resp = client.chat.completions.create(
                    model=settings.resolved_model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1200,
                    temperature=0.1,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                logger.warning("Groq RCA failed: %s", exc)

        return None

    def _parse_llm_response(
        self, response_text: str, ctx: dict[str, Any]
    ) -> RootCauseAnalysis | None:
        """Parse and validate LLM JSON response, returning None on parse failure."""
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not json_match:
            logger.warning("LLM response has no JSON object")
            return None
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.warning("LLM returned malformed JSON")
            return None

        # Validate required fields
        required = ["causal_chain", "root_cause", "confidence", "recommended_actions"]
        if not all(k in data for k in required):
            logger.warning("LLM response missing required fields")
            return None

        causal_chain = [
            CausalStep(
                sequence=s.get("sequence", i + 1),
                event=str(s.get("event", "")),
                evidence=str(s.get("evidence", "")),
            )
            for i, s in enumerate(data.get("causal_chain", []))
        ]

        return RootCauseAnalysis(
            service_name=ctx["service_name"],
            region=ctx.get("region"),
            causal_chain=causal_chain,
            root_cause=str(data["root_cause"]),
            confidence=float(data.get("confidence", 0.7)),
            evidence=[
                f"Error rate: {ctx['errors']['error_rate']*100:.2f}%",
                f"P95 latency: {ctx['latency']['p95']:.0f}ms",
                f"Anomalies: {len(ctx['anomalies'])} detected",
            ],
            recommended_actions=list(data.get("recommended_actions", [])),
            runbook_references=list({c["source"] for c in ctx.get("runbook_chunks", [])}),
            estimated_mttr_minutes=int(data.get("estimated_mttr_minutes", 60)),
            severity="SEV-2" if ctx["errors"]["error_rate"] >= 0.05 else "SEV-3",
            generation_method="llm",
        )
