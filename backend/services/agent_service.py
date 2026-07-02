"""Tool-using AI platform troubleshooting agent."""

from __future__ import annotations

from typing import Any

from backend.services.anomaly_detector import AnomalyDetector
from backend.services.incident_generator import IncidentGenerator
from backend.services.log_analyzer import LogAnalyzer
from backend.services.rag_service import RAGService


class ReliabilityAgent:
    def __init__(self) -> None:
        self.rag = RAGService()
        self.logs = LogAnalyzer()
        self.anomalies = AnomalyDetector()
        self.incidents = IncidentGenerator()

    def search_docs(self, query: str) -> list[dict[str, Any]]:
        return self.rag.retrieve(query)

    def query_logs(self, service_name: str, region: str | None = None, time_window: str | None = None) -> dict[str, Any]:
        return {
            "errors": self.logs.summarize_errors(service_name, region),
            "latency": self.logs.calculate_latency_summary(service_name, region),
            "top_error_types": self.logs.find_top_error_types(service_name, region),
            "deployment_failures": self.logs.identify_deployment_related_failures(service_name, region),
            "time_window": time_window or "all_available_data",
        }

    def detect_service_anomalies(self, service_name: str, metric_name: str | None = None, region: str | None = None) -> dict[str, Any]:
        return {
            "health_score": self.anomalies.get_service_health_score(service_name, region),
            "anomalies": self.anomalies.detect(service_name, metric_name, region),
        }

    def summarize_incident(self, service_name: str, region: str | None = None) -> dict[str, Any]:
        return self.incidents.full_incident(service_name, region)

    def generate_fix_checklist(self, error_type: str) -> list[str]:
        return self.incidents.generate_action_plan("payment-service" if error_type == "DB_CONNECTION_TIMEOUT" else "", error_type)

    def answer(self, query: str, service_name: str | None = None, region: str | None = None, time_window: str | None = None) -> dict[str, Any]:
        inferred_service = service_name or self._infer_service(query) or "payment-service"
        docs = self.search_docs(query)
        log_summary = self.query_logs(inferred_service, region, time_window)
        anomaly_summary = self.detect_service_anomalies(inferred_service, region=region)
        incident = self.summarize_incident(inferred_service, region)

        errors = log_summary["errors"]
        latency = log_summary["latency"]
        top_error = errors["top_errors"][0]["error_type"] if errors["top_errors"] else "UNKNOWN"
        deployment_failures = log_summary["deployment_failures"]
        deployment_hint = deployment_failures[0] if deployment_failures else {}
        severity = "SEV-2" if errors["error_rate"] >= 0.05 or latency["p95"] >= 900 else "SEV-3"

        incident_error_rate = deployment_hint.get("error_rate", errors["error_rate"]) if deployment_hint else errors["error_rate"]
        incident_p95 = deployment_hint.get("p95_latency", latency["p95"]) if deployment_hint else latency["p95"]
        article = "an" if top_error[:1].lower() in {"a", "e", "i", "o", "u"} else "a"

        scope = f"{inferred_service} in {region}" if region else f"{inferred_service} across all regions"
        answer = (
            f"{scope} is showing {article} {top_error} reliability pattern. "
            f"The riskiest slice is at {incident_error_rate * 100:.2f}% error rate with p95 latency near {incident_p95:.0f} ms. "
        )
        if deployment_hint:
            answer += (
                f"It is most correlated with deployment {deployment_hint.get('deployment_version')} "
                f"in {deployment_hint.get('region')}. "
            )
        answer += incident["root_cause_hypothesis"]

        evidence = [
            f"Scope: {scope}; {errors['total_logs']} logs analyzed.",
            f"Error rate: {errors['error_rate'] * 100:.2f}%; p95 latency: {latency['p95']:.0f} ms.",
            f"Primary error signature: {top_error}.",
            f"Anomaly check: {len(anomaly_summary['anomalies'])} signals; health score {anomaly_summary['health_score']}.",
        ]
        if deployment_hint:
            evidence.append(
                f"Deployment slice {deployment_hint.get('deployment_version')} / {deployment_hint.get('region')}: "
                f"{deployment_hint.get('error_rate') * 100:.2f}% error rate, p95 {deployment_hint.get('p95_latency'):.0f} ms."
            )
        if docs:
            evidence.append(f"Runbook guidance retrieved from {', '.join(sorted({d['source'] for d in docs}))}.")

        return {
            "answer": answer,
            "evidence": evidence,
            "sources": docs,
            "recommended_actions": incident["action_plan"],
            "severity": severity,
        }

    @staticmethod
    def _infer_service(query: str) -> str | None:
        services = [
            "auth-service",
            "payment-service",
            "matchmaking-service",
            "player-profile-service",
            "notification-service",
            "game-session-service",
            "leaderboard-service",
        ]
        query_lower = query.lower()
        for service in services:
            if service in query_lower:
                return service
        return None
