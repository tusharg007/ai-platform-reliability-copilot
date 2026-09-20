"""Evaluation framework for the AI Platform Reliability Copilot.

Runs systematic evaluations measuring:
  - Groundedness:           % of answer claims supported by evidence
  - Relevance:              Does the answer address the actual query?
  - Completeness:           Are critical action items present?
  - Hallucination Rate:     % of fabricated facts
  - Retrieval Precision@K:  Relevant docs in top-K results
  - E2E Latency:            Response time in milliseconds

Usage::

    python -m evals.runner --dataset=golden_set
    python -m evals.runner --dataset=adversarial --threshold-groundedness=0.95
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).parent


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvalCase:
    """A single evaluation test case."""
    query: str
    service_name: str | None = None
    region: str | None = None
    expected_service: str | None = None
    expected_error_type: str | None = None
    expected_sources: list[str] = field(default_factory=list)
    expected_severity: str | None = None
    expected_action_keywords: list[str] = field(default_factory=list)
    is_adversarial: bool = False
    dataset: str = "golden_set"


@dataclass
class EvalMetrics:
    """Quality metrics for a single evaluation run."""
    groundedness: float = 0.0
    relevance: float = 0.0
    completeness: float = 0.0
    hallucination: float = 0.0
    latency_ms: float = 0.0
    retrieval_precision: float = 0.0
    passed: bool = False


@dataclass
class EvalResult:
    """Complete result of evaluating one case against the copilot."""
    case: EvalCase
    metrics: EvalMetrics
    response: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ─────────────────────────────────────────────────────────────────────────────
#  Judges
# ─────────────────────────────────────────────────────────────────────────────

class GroundednessJudge:
    """Evaluates whether response claims are grounded in provided evidence."""

    # Factual claim patterns to extract and verify
    _METRIC_PATTERN = re.compile(r"(\d+\.?\d*)\s*(%|ms|/100|minutes?|min)")
    _SERVICE_PATTERN = re.compile(
        r"(auth-service|payment-service|matchmaking-service|"
        r"player-profile-service|notification-service|"
        r"game-session-service|leaderboard-service)"
    )
    _ERROR_PATTERN = re.compile(
        r"(DB_CONNECTION_TIMEOUT|AUTH_TOKEN_EXPIRED|UPSTREAM_503|"
        r"CACHE_MISS_STORM|RATE_LIMIT_EXCEEDED|MATCHMAKING_QUEUE_TIMEOUT)"
    )
    _VERSION_PATTERN = re.compile(r"v\d+\.\d+\.\d+")

    def score(
        self, answer: str, evidence: list[str], sources: list[dict]
    ) -> float:
        """Check what fraction of answer claims are grounded in evidence.

        Returns score 0.0 (no grounding) to 1.0 (fully grounded).
        """
        if not answer:
            return 0.0

        evidence_text = " ".join(evidence) + " ".join(
            s.get("text", "") for s in sources
        )
        evidence_text = evidence_text.lower()

        claims_total = 0
        claims_verified = 0

        # Check service mentions
        for svc in self._SERVICE_PATTERN.findall(answer):
            claims_total += 1
            if svc in evidence_text:
                claims_verified += 1

        # Check error type mentions
        for err in self._ERROR_PATTERN.findall(answer):
            claims_total += 1
            if err.lower() in evidence_text:
                claims_verified += 1

        # Check deployment version mentions
        for ver in self._VERSION_PATTERN.findall(answer):
            claims_total += 1
            if ver in evidence_text:
                claims_verified += 1

        # Check metric values (numbers with units)
        for val, unit in self._METRIC_PATTERN.findall(answer):
            claims_total += 1
            # Look for the number in evidence (within 10% tolerance)
            try:
                num = float(val)
                # Search evidence for this value or nearby values
                evidence_nums = [
                    float(m) for m in re.findall(r"\d+\.?\d*", evidence_text)
                ]
                if any(abs(n - num) / max(num, 1) < 0.15 for n in evidence_nums):
                    claims_verified += 1
            except ValueError:
                claims_verified += 1  # Non-numeric, assume ok

        if claims_total == 0:
            # No specific factual claims — return moderate score
            return 0.7

        return round(claims_verified / claims_total, 3)


class RelevanceJudge:
    """Evaluates whether the answer addresses the actual query."""

    def score(
        self,
        query: str,
        answer: str,
        expected_service: str | None = None,
    ) -> float:
        """Score relevance 0.0–1.0 based on query–answer alignment."""
        if not answer or len(answer) < 50:
            return 0.1

        score = 0.0
        query_lower = query.lower()
        answer_lower = answer.lower()

        # Service mentioned
        if expected_service and expected_service in answer_lower:
            score += 0.3
        elif expected_service:
            score += 0.0
        else:
            score += 0.2  # No specific service expected

        # Question type alignment
        if "why" in query_lower and (
            "because" in answer_lower or "caused" in answer_lower or "due to" in answer_lower
        ):
            score += 0.3
        elif "what" in query_lower or "how" in query_lower:
            score += 0.25
        else:
            score += 0.2

        # Answer specificity (longer, more specific answers score higher)
        if len(answer) > 500:
            score += 0.2
        elif len(answer) > 200:
            score += 0.15
        else:
            score += 0.05

        # Action items present
        if "recommend" in answer_lower or "action" in answer_lower or "step" in answer_lower:
            score += 0.2

        return min(round(score, 3), 1.0)


class HallucinationDetector:
    """Detects fabricated information in copilot responses."""

    KNOWN_SERVICES = {
        "auth-service", "payment-service", "matchmaking-service",
        "player-profile-service", "notification-service",
        "game-session-service", "leaderboard-service",
    }
    KNOWN_REGIONS = {"us-east", "us-west", "eu-central", "ap-south"}
    KNOWN_ERROR_TYPES = {
        "DB_CONNECTION_TIMEOUT", "AUTH_TOKEN_EXPIRED", "UPSTREAM_503",
        "CACHE_MISS_STORM", "RATE_LIMIT_EXCEEDED", "MATCHMAKING_QUEUE_TIMEOUT",
    }
    KNOWN_VERSIONS = {"v1.8.2", "v2.0.9", "v2.1.3", "v2.1.4"}

    def score(self, answer: str, evidence: list[str]) -> float:
        """Return hallucination rate 0.0 (none) to 1.0 (all fabricated)."""
        if not answer:
            return 0.0

        hallucinations = 0
        total_claims = 0
        evidence_text = " ".join(evidence)

        # Check service names
        svc_pattern = re.compile(
            r"\b([a-z]+-service)\b", re.IGNORECASE
        )
        for svc_match in svc_pattern.findall(answer):
            svc = svc_match.lower()
            total_claims += 1
            if svc not in self.KNOWN_SERVICES:
                hallucinations += 1

        # Check region names
        rgn_pattern = re.compile(r"\b(us-east|us-west|eu-central|ap-south)\b", re.IGNORECASE)
        # Check for unknown region-like patterns
        unknown_rgn = re.compile(r"\b(eu-west|ap-north|us-central|sa-east)\b", re.IGNORECASE)
        for _ in unknown_rgn.findall(answer):
            hallucinations += 1
            total_claims += 1

        # Check version numbers — if not in known set, flag
        version_pattern = re.compile(r"\bv\d+\.\d+\.\d+\b")
        for ver in version_pattern.findall(answer):
            total_claims += 1
            if ver not in self.KNOWN_VERSIONS and ver not in evidence_text:
                hallucinations += 1

        if total_claims == 0:
            return 0.0

        return round(hallucinations / total_claims, 3)


class CompletenessJudge:
    """Evaluates whether critical action items are present in the response."""

    def score(
        self, actions: list[str], expected_keywords: list[str]
    ) -> float:
        """Fraction of expected keywords found in action items."""
        if not expected_keywords:
            return 1.0 if actions else 0.5

        actions_text = " ".join(actions).lower()
        found = sum(1 for kw in expected_keywords if kw.lower() in actions_text)
        return round(found / len(expected_keywords), 3)


class RetrievalQualityJudge:
    """Evaluates RAG retrieval accuracy."""

    def precision_at_k(
        self,
        retrieved_sources: list[dict],
        expected_sources: list[str],
        k: int = 4,
    ) -> float:
        """Fraction of retrieved docs that are in the expected set."""
        if not expected_sources:
            return 1.0
        top_k = retrieved_sources[:k]
        retrieved_names = {s.get("source", "") for s in top_k}
        expected_set = set(expected_sources)
        hits = len(retrieved_names & expected_set)
        return round(hits / max(len(top_k), 1), 3)

    def reciprocal_rank(
        self,
        retrieved_sources: list[dict],
        expected_sources: list[str],
    ) -> float:
        """Reciprocal rank of the first relevant result."""
        if not expected_sources:
            return 1.0
        expected_set = set(expected_sources)
        for rank, src in enumerate(retrieved_sources, start=1):
            if src.get("source", "") in expected_set:
                return round(1.0 / rank, 3)
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  Eval Runner
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    "groundedness": 0.80,
    "relevance": 0.70,
    "completeness": 0.60,
    "hallucination": 0.10,   # Must be BELOW this
    "latency_ms": 10_000.0,  # Must be BELOW this
    "retrieval_precision": 0.50,
}


class EvalRunner:
    """Orchestrates evaluation runs against the copilot agent."""

    def __init__(self, datasets_dir: Path | None = None) -> None:
        self._datasets_dir = datasets_dir or (EVALS_DIR / "datasets")
        self._groundedness = GroundednessJudge()
        self._relevance = RelevanceJudge()
        self._hallucination = HallucinationDetector()
        self._completeness = CompletenessJudge()
        self._retrieval = RetrievalQualityJudge()

    def load_dataset(self, dataset_name: str) -> list[EvalCase]:
        """Load evaluation cases from a JSONL file."""
        path = self._datasets_dir / f"{dataset_name}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"Eval dataset not found: {path}")
        cases = []
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                data = json.loads(line)
                cases.append(EvalCase(**{k: v for k, v in data.items() if k in EvalCase.__dataclass_fields__}))
        return cases

    def evaluate_case(self, case: EvalCase) -> EvalResult:
        """Run a single eval case through the agent and score it."""
        from backend.services.agent_service import ReliabilityAgent

        agent = ReliabilityAgent()
        errors: list[str] = []
        response: dict[str, Any] = {}

        t0 = time.perf_counter()
        try:
            response = agent.answer(
                query=case.query,
                service_name=case.service_name,
                region=case.region,
            )
        except Exception as exc:
            errors.append(f"Agent error: {exc}")

        latency_ms = (time.perf_counter() - t0) * 1000

        answer = response.get("answer", "")
        evidence = response.get("evidence", [])
        sources = response.get("sources", [])
        actions = response.get("recommended_actions", [])

        # Score each dimension
        groundedness = self._groundedness.score(answer, evidence, sources)
        relevance = self._relevance.score(answer, case.query, case.expected_service)
        hallucination = self._hallucination.score(answer, evidence)
        completeness = self._completeness.score(actions, case.expected_action_keywords)
        precision = self._retrieval.precision_at_k(sources, case.expected_sources)

        metrics = EvalMetrics(
            groundedness=groundedness,
            relevance=relevance,
            completeness=completeness,
            hallucination=hallucination,
            latency_ms=round(latency_ms, 1),
            retrieval_precision=precision,
        )

        return EvalResult(case=case, metrics=metrics, response=response, errors=errors)

    def _case_passes(
        self, result: EvalResult, thresholds: dict[str, float]
    ) -> bool:
        m = result.metrics
        return (
            m.groundedness >= thresholds.get("groundedness", 0.80)
            and m.relevance >= thresholds.get("relevance", 0.70)
            and m.completeness >= thresholds.get("completeness", 0.60)
            and m.hallucination <= thresholds.get("hallucination", 0.10)
            and m.latency_ms <= thresholds.get("latency_ms", 10_000.0)
            and m.retrieval_precision >= thresholds.get("retrieval_precision", 0.50)
            and not result.errors
        )

    def run_suite(
        self,
        dataset_name: str = "golden_set",
        thresholds: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Run the full evaluation suite and return aggregated results."""
        effective_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        cases = self.load_dataset(dataset_name)
        results: list[EvalResult] = []

        print(f"\n🔍 Running eval suite: {dataset_name} ({len(cases)} cases)")
        for i, case in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {case.query[:60]}...")
            result = self.evaluate_case(case)
            result.metrics.passed = self._case_passes(result, effective_thresholds)
            results.append(result)

        passed = [r for r in results if r.metrics.passed]
        failed = [r for r in results if not r.metrics.passed]

        avg = lambda attr: round(
            sum(getattr(r.metrics, attr) for r in results) / max(len(results), 1), 3
        )

        return {
            "dataset": dataset_name,
            "total_cases": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "pass_rate": round(len(passed) / max(len(results), 1), 3),
            "avg_metrics": {
                "groundedness": avg("groundedness"),
                "relevance": avg("relevance"),
                "completeness": avg("completeness"),
                "hallucination": avg("hallucination"),
                "latency_ms": avg("latency_ms"),
                "retrieval_precision": avg("retrieval_precision"),
            },
            "thresholds": effective_thresholds,
            "failures": [
                {
                    "query": r.case.query[:80],
                    "groundedness": r.metrics.groundedness,
                    "relevance": r.metrics.relevance,
                    "hallucination": r.metrics.hallucination,
                    "errors": r.errors,
                }
                for r in failed
            ],
        }

    def generate_report(
        self,
        results: dict[str, Any],
        output_path: Path | None = None,
    ) -> str:
        """Generate a markdown eval report."""
        avg = results["avg_metrics"]
        pass_rate = results["pass_rate"]
        status = "✅ PASSED" if pass_rate >= 0.85 else "❌ FAILED"

        report = f"""# Eval Report — {results['dataset']}

Generated: {datetime.utcnow().isoformat()}Z

## Summary {status}

| Metric | Score | Threshold |
|---|---|---|
| Pass Rate | **{pass_rate:.1%}** | ≥ 85% |
| Groundedness | {avg['groundedness']:.3f} | ≥ {results['thresholds']['groundedness']} |
| Relevance | {avg['relevance']:.3f} | ≥ {results['thresholds']['relevance']} |
| Completeness | {avg['completeness']:.3f} | ≥ {results['thresholds']['completeness']} |
| Hallucination | {avg['hallucination']:.3f} | ≤ {results['thresholds']['hallucination']} |
| Latency (ms) | {avg['latency_ms']:.0f} | ≤ {results['thresholds']['latency_ms']:.0f} |
| Retrieval Precision | {avg['retrieval_precision']:.3f} | ≥ {results['thresholds']['retrieval_precision']} |

**Cases:** {results['total_cases']} total — {results['passed']} passed, {results['failed']} failed

## Failures
"""
        for f in results.get("failures", []):
            report += f"\n- **{f['query']}**\n"
            report += f"  - Groundedness: {f['groundedness']:.2f}, Relevance: {f['relevance']:.2f}, Hallucination: {f['hallucination']:.2f}\n"
            if f["errors"]:
                report += f"  - Errors: {'; '.join(f['errors'])}\n"

        if output_path:
            output_path.write_text(report, encoding="utf-8")
        return report


# ─────────────────────────────────────────────────────────────────────────────
#  CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run AI Copilot eval suite")
    parser.add_argument("--dataset", default="golden_set", help="Dataset name")
    parser.add_argument("--threshold-groundedness", type=float, default=0.80)
    parser.add_argument("--threshold-hallucination", type=float, default=0.10)
    parser.add_argument("--threshold-relevance", type=float, default=0.70)
    parser.add_argument("--output", default=None, help="Report output path")
    args = parser.parse_args()

    runner = EvalRunner()
    results = runner.run_suite(
        dataset_name=args.dataset,
        thresholds={
            "groundedness": args.threshold_groundedness,
            "hallucination": args.threshold_hallucination,
            "relevance": args.threshold_relevance,
        },
    )
    report = runner.generate_report(
        results,
        output_path=Path(args.output) if args.output else None,
    )
    print(report)

    # Exit with non-zero if below threshold (for CI gate)
    import sys
    sys.exit(0 if results["pass_rate"] >= 0.85 else 1)
