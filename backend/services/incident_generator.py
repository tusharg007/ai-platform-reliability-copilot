"""Incident summary and action-plan generation."""

from __future__ import annotations

from typing import Any

from backend.services.anomaly_detector import AnomalyDetector
from backend.services.log_analyzer import LogAnalyzer


class IncidentGenerator:
    def __init__(self) -> None:
        self.logs = LogAnalyzer()
        self.anomalies = AnomalyDetector()

    def generate_incident_summary(self, service_name: str, region: str | None = None) -> str:
        errors = self.logs.summarize_errors(service_name, region)
        latency = self.logs.calculate_latency_summary(service_name, region)
        top_errors = errors.get("top_errors", [])
        leading_error = top_errors[0]["error_type"] if top_errors else "UNKNOWN"
        return (
            f"{service_name} in {region or 'all regions'} is showing {errors['error_rate'] * 100:.2f}% error rate "
            f"with p95 latency at {latency['p95']:.0f} ms. Leading error signature: {leading_error}."
        )

    def generate_root_cause_hypothesis(self, service_name: str, region: str | None = None) -> str:
        deployment_failures = self.logs.identify_deployment_related_failures(service_name, region)
        if deployment_failures:
            top = deployment_failures[0]
            return (
                f"Most likely cause is a deployment-correlated regression in {top['deployment_version']} "
                f"for {top['region']}, where error rate is {top['error_rate'] * 100:.2f}% "
                f"and p95 latency is {top['p95_latency']:.0f} ms."
            )
        return "No single deployment regression is conclusive; inspect downstream dependency health and regional capacity."

    def generate_action_plan(self, service_name: str, error_type: str | None = None) -> list[str]:
        if error_type == "DB_CONNECTION_TIMEOUT":
            return [
                "Check database connection pool usage and slow queries.",
                "Compare deployment v2.1.4 against the previous stable version.",
                "Temporarily increase pool limits only if database capacity is healthy.",
                "Roll back the deployment if error rate remains above 5 percent for 15 minutes.",
            ]
        if error_type == "AUTH_TOKEN_EXPIRED":
            return [
                "Check token issuer health, signing key refresh, and client token expiry behavior.",
                "Compare auth-related configuration changes between the current and previous deployment.",
                "Inspect regional identity-provider latency and 401 or 403 spikes.",
                "Escalate to identity platform owners if authentication failures stay elevated.",
            ]
        return [
            "Segment failures by service, region, and deployment version.",
            "Search logs for the dominant error type and trace IDs.",
            "Check recent deployments and downstream dependency dashboards.",
            "Escalate if customer-facing error rate stays above service threshold.",
        ]

    def generate_postmortem_template(self, service_name: str) -> str:
        return (
            f"## Postmortem: {service_name}\n\n"
            "### Impact\nDescribe affected users, regions, and duration.\n\n"
            "### Timeline\n- Detection:\n- Mitigation:\n- Recovery:\n\n"
            "### Root Cause\nSummarize the confirmed trigger and contributing factors.\n\n"
            "### Corrective Actions\n- Owner / due date / action item\n"
        )

    def full_incident(self, service_name: str, region: str | None = None) -> dict[str, Any]:
        errors = self.logs.summarize_errors(service_name, region)
        leading_error = errors["top_errors"][0]["error_type"] if errors["top_errors"] else None
        return {
            "summary": self.generate_incident_summary(service_name, region),
            "root_cause_hypothesis": self.generate_root_cause_hypothesis(service_name, region),
            "action_plan": self.generate_action_plan(service_name, leading_error),
            "postmortem_template": self.generate_postmortem_template(service_name),
        }
