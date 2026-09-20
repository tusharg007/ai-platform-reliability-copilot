"""Multi-dimensional risk scoring for incidents and clusters.

Risk Score = weighted combination of 5 orthogonal dimensions:
  - Blast Radius   (0-1): breadth of impact across services × regions
  - Velocity       (0-1): rate of escalation / acceleration of error signals
  - SLO Burn Rate  (0-1): speed at which error budget is being consumed
  - Historical     (0-1): severity of past incidents with same signature
  - Revenue Impact (0-1): business criticality of affected service tier

Weights are configurable via environment variables (RISK_W_* env vars).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from backend.services.anomaly_detector import AnomalyDetector
from backend.services.log_analyzer import LogAnalyzer
from backend.utils.config import DATA_DIR, get_settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Service Tier Map (revenue/criticality ordering)
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_TIERS: dict[str, float] = {
    "payment-service":        1.00,  # Direct revenue — highest impact
    "auth-service":           0.90,  # Login/access-critical
    "game-session-service":   0.80,  # Active gameplay
    "matchmaking-service":    0.70,  # Core engagement loop
    "player-profile-service": 0.50,  # Profile reads / inventory
    "leaderboard-service":    0.30,  # Non-critical display
    "notification-service":   0.20,  # Async, non-blocking
}

_KNOWN_SERVICES = list(SERVICE_TIERS.keys())
_TOTAL_REGIONS = 4  # us-east, us-west, eu-central, ap-south


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskAssessment:
    """Complete multi-dimensional risk assessment for an incident."""
    service_name: str
    region: str | None
    error_type: str | None
    blast_radius_score: float
    velocity_score: float
    slo_burn_score: float
    historical_score: float
    revenue_score: float
    composite_score: float
    severity: str
    contributing_factors: list[str] = field(default_factory=list)
    calculated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["contributing_factors"] = self.contributing_factors
        return d


# ─────────────────────────────────────────────────────────────────────────────
#  RiskScorer
# ─────────────────────────────────────────────────────────────────────────────

class RiskScorer:
    """Computes composite risk scores for reliability incidents.

    Example usage::

        scorer = RiskScorer()
        assessment = scorer.score_incident("payment-service", "ap-south", "DB_CONNECTION_TIMEOUT")
        print(assessment.severity)   # "SEV-1"
        print(assessment.composite_score)  # 0.91
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        settings = get_settings()
        self._weights = weights or settings.risk_score_weights
        self._log_analyzer = LogAnalyzer()
        self._anomaly_detector = AnomalyDetector()
        self._slo_target = settings.slo_availability_target

    # ── Dimension Calculators ──────────────────────────────────────────────────

    def _calculate_blast_radius(
        self, service_name: str, region: str | None
    ) -> tuple[float, str]:
        """Score 0–1 representing breadth of impact.

        - Single service, single region  → low score
        - Multiple services / regions    → high score
        """
        services_affected = 1  # The current service always counts
        regions_affected = 1 if region else _TOTAL_REGIONS  # Unknown = assume all

        # Check if anomalies exist for other services too
        all_services = self._log_analyzer.service_list()
        for svc in all_services:
            if svc == service_name:
                continue
            try:
                errors = self._log_analyzer.summarize_errors(svc)
                if errors["error_rate"] >= 0.05:
                    services_affected += 1
            except Exception:
                pass

        svc_score = min(services_affected / len(_KNOWN_SERVICES), 1.0)
        rgn_score = min(regions_affected / _TOTAL_REGIONS, 1.0)
        score = round(svc_score * 0.5 + rgn_score * 0.5, 3)

        explanation = (
            f"Blast radius: {services_affected}/{len(_KNOWN_SERVICES)} services affected, "
            f"{regions_affected}/{_TOTAL_REGIONS} regions affected"
        )
        return score, explanation

    def _calculate_velocity(
        self, service_name: str, region: str | None
    ) -> tuple[float, str]:
        """Score 0–1 representing rate of error escalation.

        Compares recent error rate to the rolling baseline.
        Rapid acceleration → high velocity score.
        """
        try:
            anomalies = self._anomaly_detector.detect(service_name, "error_rate", region)
            if not anomalies:
                return 0.1, "Velocity: no active error rate anomalies"

            high_count = sum(1 for a in anomalies if a.get("severity") == "high")
            medium_count = sum(1 for a in anomalies if a.get("severity") == "medium")

            # Normalise: 3+ high anomalies = max velocity
            score = min((high_count * 0.3 + medium_count * 0.1), 1.0)
            explanation = (
                f"Velocity: {high_count} high + {medium_count} medium error_rate anomalies "
                f"→ score {score:.2f}"
            )
            return round(score, 3), explanation
        except Exception:
            return 0.2, "Velocity: estimated from anomaly count"

    def _calculate_slo_burn(
        self, service_name: str, region: str | None
    ) -> tuple[float, str]:
        """Score 0–1 based on error budget consumption rate.

        Assumes 99.9% availability SLO (0.1% error budget per 30-day window).
        If current error rate would exhaust the budget in < 1 day → score = 1.0.
        """
        try:
            errors = self._log_analyzer.summarize_errors(service_name, region)
            current_error_rate = errors["error_rate"]

            error_budget = 1.0 - self._slo_target          # e.g. 0.001 for 99.9%
            if current_error_rate <= 0:
                return 0.0, "SLO burn: no errors detected"

            # Time to exhaust budget = budget / current_burn_rate (in 30-day fractions)
            # If TTB < 1 day (1/30 of window) → score = 1.0
            ttb_fraction = error_budget / current_error_rate  # fraction of 30-day window
            ttb_days = ttb_fraction * 30

            if ttb_days < 1:
                score = 1.0
            elif ttb_days < 7:
                score = round(1.0 - (ttb_days - 1) / 6.0, 3)
            elif ttb_days < 30:
                score = round(0.3 * (1 - (ttb_days - 7) / 23.0), 3)
            else:
                score = 0.0

            explanation = (
                f"SLO burn: error_rate={current_error_rate:.3f} burns budget in "
                f"~{ttb_days:.1f} days → score {score:.2f}"
            )
            return score, explanation
        except Exception:
            return 0.3, "SLO burn: estimated from error signature"

    def _calculate_historical_severity(
        self, service_name: str, error_type: str | None
    ) -> tuple[float, str]:
        """Score 0–1 based on past incident severity for this signature.

        SEV-1 history → 1.0, SEV-2 → 0.75, SEV-3 → 0.45, no history → 0.20
        """
        incidents_path = DATA_DIR / "incidents.csv"
        if not incidents_path.exists():
            return 0.2, "Historical: no incident history available"

        try:
            df = pd.read_csv(incidents_path)
            mask = df["service_name"] == service_name
            if error_type:
                mask = mask | (df["issue_type"] == error_type)
            matched = df[mask]

            if matched.empty:
                return 0.2, f"Historical: no prior incidents for {service_name}/{error_type}"

            severity_weights = {"SEV-1": 1.0, "SEV-2": 0.75, "SEV-3": 0.45, "SEV-4": 0.2}
            scores = [severity_weights.get(s, 0.2) for s in matched["severity"].tolist()]
            score = round(max(scores), 3)  # Worst-case historical severity

            worst_sev = matched.loc[matched["severity"].map(severity_weights).idxmax(), "severity"]
            avg_duration = round(matched["duration_minutes"].mean(), 0)
            explanation = (
                f"Historical: worst past incident was {worst_sev}, "
                f"avg MTTR {avg_duration:.0f} min → score {score}"
            )
            return score, explanation
        except Exception as exc:
            logger.debug("Historical severity lookup failed: %s", exc)
            return 0.2, "Historical: lookup unavailable"

    def _calculate_revenue_impact(self, service_name: str) -> tuple[float, str]:
        """Score 0–1 based on the service's business criticality tier."""
        score = SERVICE_TIERS.get(service_name, 0.3)
        explanation = f"Revenue impact: {service_name} is tier {score:.2f}"
        return score, explanation

    # ── Severity Classification ───────────────────────────────────────────────

    @staticmethod
    def classify_severity(score: float) -> str:
        """Map composite score to SEV classification.

        - SEV-1: score ≥ 0.85  (critical, immediate response)
        - SEV-2: score ≥ 0.60  (major, 15-min SLO)
        - SEV-3: score ≥ 0.35  (significant, 1-hour SLO)
        - SEV-4: score < 0.35  (low, best-effort)
        """
        if score >= 0.85:
            return "SEV-1"
        if score >= 0.60:
            return "SEV-2"
        if score >= 0.35:
            return "SEV-3"
        return "SEV-4"

    # ── Main Scoring Methods ──────────────────────────────────────────────────

    def score_incident(
        self,
        service_name: str,
        region: str | None = None,
        error_type: str | None = None,
    ) -> RiskAssessment:
        """Compute the full multi-dimensional risk assessment for an incident.

        Args:
            service_name: Name of the affected microservice.
            region:       Cloud region (None = all regions).
            error_type:   Primary error type driving the incident.

        Returns:
            A :class:`RiskAssessment` with per-dimension scores, composite,
            severity, and human-readable contributing factors.
        """
        weights = self._weights
        factors: list[str] = []

        br_score, br_explain = self._calculate_blast_radius(service_name, region)
        vel_score, vel_explain = self._calculate_velocity(service_name, region)
        slo_score, slo_explain = self._calculate_slo_burn(service_name, region)
        hist_score, hist_explain = self._calculate_historical_severity(service_name, error_type)
        rev_score, rev_explain = self._calculate_revenue_impact(service_name)

        factors.extend([br_explain, vel_explain, slo_explain, hist_explain, rev_explain])

        composite = round(
            br_score   * weights["blast_radius"]
            + vel_score  * weights["velocity"]
            + slo_score  * weights["slo_burn"]
            + hist_score * weights["historical"]
            + rev_score  * weights["revenue"],
            4,
        )
        severity = self.classify_severity(composite)

        assessment = RiskAssessment(
            service_name=service_name,
            region=region,
            error_type=error_type,
            blast_radius_score=br_score,
            velocity_score=vel_score,
            slo_burn_score=slo_score,
            historical_score=hist_score,
            revenue_score=rev_score,
            composite_score=composite,
            severity=severity,
            contributing_factors=factors,
        )
        logger.info(
            "Risk scored: %s/%s composite=%.3f sev=%s",
            service_name, region, composite, severity
        )
        return assessment

    def score_cluster(self, cluster: Any) -> RiskAssessment:
        """Aggregate risk across all members of an incident cluster.

        Applies a correlation multiplier when multiple critical-path services
        are affected simultaneously (correlated failure amplifies risk).
        """
        member_incidents = getattr(cluster, "member_incidents", [])
        if not member_incidents:
            return self.score_incident(
                getattr(cluster, "centroid_service", "unknown")
            )

        # Score each member, take the max composite
        assessments = [
            self.score_incident(
                m.service_name,
                m.region,
                m.error_type,
            )
            for m in member_incidents
        ]
        max_assessment = max(assessments, key=lambda a: a.composite_score)

        # Correlation multiplier: multiple critical services → amplify score
        critical_services = [
            m for m in member_incidents
            if SERVICE_TIERS.get(m.service_name, 0) >= 0.7
        ]
        if len(critical_services) >= 2:
            multiplier = min(1.0 + 0.15 * (len(critical_services) - 1), 1.4)
            max_assessment.composite_score = min(
                round(max_assessment.composite_score * multiplier, 4), 1.0
            )
            max_assessment.severity = self.classify_severity(max_assessment.composite_score)
            max_assessment.contributing_factors.append(
                f"Correlation multiplier ×{multiplier:.2f}: "
                f"{len(critical_services)} critical-path services in same cluster"
            )

        return max_assessment

    def fleet_risk_summary(self) -> dict[str, Any]:
        """Compute risk scores for all monitored services.

        Returns a fleet-wide risk summary including per-service scores,
        the highest-risk service, and an overall fleet risk score.
        """
        services = self._log_analyzer.service_list()
        per_service: list[dict] = []
        max_score = 0.0
        max_service = ""

        for svc in services:
            try:
                assessment = self.score_incident(svc)
                d = {
                    "service_name": svc,
                    "composite_score": assessment.composite_score,
                    "severity": assessment.severity,
                    "blast_radius_score": assessment.blast_radius_score,
                    "velocity_score": assessment.velocity_score,
                    "slo_burn_score": assessment.slo_burn_score,
                    "top_factor": assessment.contributing_factors[0] if assessment.contributing_factors else "",
                }
                per_service.append(d)
                if assessment.composite_score > max_score:
                    max_score = assessment.composite_score
                    max_service = svc
            except Exception as exc:
                logger.debug("Risk scoring failed for %s: %s", svc, exc)

        # Group by severity
        severity_groups: dict[str, list[str]] = {"SEV-1": [], "SEV-2": [], "SEV-3": [], "SEV-4": []}
        for s in per_service:
            severity_groups[s["severity"]].append(s["service_name"])

        fleet_score = round(
            sum(s["composite_score"] for s in per_service) / max(len(per_service), 1), 4
        )

        return {
            "fleet_risk_score": fleet_score,
            "fleet_severity": self.classify_severity(fleet_score),
            "highest_risk_service": max_service,
            "highest_risk_score": round(max_score, 4),
            "services_by_severity": severity_groups,
            "per_service_risk": sorted(per_service, key=lambda s: s["composite_score"], reverse=True),
        }
