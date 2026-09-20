"""Production runtime guardrails for the AI Platform Reliability Copilot.

Guards every request/response with:
  1. InputValidator:      Query length, injection pattern detection, service allowlist
  2. OutputValidator:     Response schema, PII detection, citation verification
  3. RateLimiter:         Token bucket per client ID
  4. CircuitBreaker:      Prevents LLM call storms on repeated failures
  5. AuditLogger:         Compliance logging of all interactions
  6. GuardrailsMiddleware: FastAPI middleware composing all guards
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Guardrail Result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    violations: list[str] = field(default_factory=list)
    sanitized_input: str | None = None
    blocked: bool = False
    reason: str | None = None

    @classmethod
    def ok(cls, sanitized: str | None = None) -> "GuardrailResult":
        return cls(passed=True, sanitized_input=sanitized)

    @classmethod
    def fail(cls, reason: str, violations: list[str] | None = None) -> "GuardrailResult":
        return cls(
            passed=False,
            blocked=True,
            reason=reason,
            violations=violations or [reason],
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Input Validator
# ─────────────────────────────────────────────────────────────────────────────

class InputValidator:
    """Validates and sanitises incoming user queries."""

    MAX_QUERY_LENGTH = 2000
    MIN_QUERY_LENGTH = 3

    KNOWN_SERVICES = {
        "auth-service", "payment-service", "matchmaking-service",
        "player-profile-service", "notification-service",
        "game-session-service", "leaderboard-service",
    }
    KNOWN_REGIONS = {"us-east", "us-west", "eu-central", "ap-south"}

    # Prompt injection patterns
    INJECTION_PATTERNS = [
        (re.compile(r"ignore\s+(previous|above|all)\s+instructions", re.IGNORECASE),
         "prompt_injection_ignore"),
        (re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
         "prompt_injection_role"),
        (re.compile(r"forget\s+(everything|all|your)", re.IGNORECASE),
         "prompt_injection_forget"),
        (re.compile(r"system\s*prompt", re.IGNORECASE),
         "system_prompt_extraction"),
        (re.compile(r"\bact\s+as\b.*\b(admin|root|system|hacker)", re.IGNORECASE),
         "privilege_escalation"),
        (re.compile(r"reveal\s+(your|the)\s+(instructions|prompt|system|api\s*key)", re.IGNORECASE),
         "secret_extraction"),
        (re.compile(r"<\s*script", re.IGNORECASE),
         "xss_attempt"),
        (re.compile(r"\{\{.*\}\}", re.DOTALL),
         "template_injection"),
        (re.compile(r"\$\{.*\}", re.DOTALL),
         "variable_injection"),
        (re.compile(r"DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET", re.IGNORECASE),
         "sql_injection"),
    ]

    def validate_query(self, query: str) -> GuardrailResult:
        """Validate a user query for length and injection patterns."""
        if not query or not query.strip():
            return GuardrailResult.fail("Query must not be empty")

        if len(query) > self.MAX_QUERY_LENGTH:
            return GuardrailResult.fail(
                f"Query exceeds maximum length ({len(query)} > {self.MAX_QUERY_LENGTH})"
            )

        if len(query) < self.MIN_QUERY_LENGTH:
            return GuardrailResult.fail(
                f"Query too short (min {self.MIN_QUERY_LENGTH} characters)"
            )

        # Check injection patterns
        for pattern, pattern_name in self.INJECTION_PATTERNS:
            if pattern.search(query):
                logger.warning("Injection attempt blocked: pattern=%s query_prefix=%s",
                               pattern_name, query[:60])
                return GuardrailResult.fail(
                    f"Query contains disallowed pattern: {pattern_name}",
                    violations=[f"injection_pattern:{pattern_name}"],
                )

        # Sanitise (strip leading/trailing whitespace, normalise unicode)
        sanitized = query.strip()
        return GuardrailResult.ok(sanitized=sanitized)

    def validate_service_name(self, service_name: str | None) -> GuardrailResult:
        """Validate service name against known services."""
        if service_name is None:
            return GuardrailResult.ok()
        if service_name not in self.KNOWN_SERVICES:
            return GuardrailResult.fail(
                f"Unknown service: '{service_name}'. Must be one of: {sorted(self.KNOWN_SERVICES)}",
                violations=[f"unknown_service:{service_name}"],
            )
        return GuardrailResult.ok()

    def validate_region(self, region: str | None) -> GuardrailResult:
        """Validate region against known regions."""
        if region is None:
            return GuardrailResult.ok()
        if region not in self.KNOWN_REGIONS:
            return GuardrailResult.fail(
                f"Unknown region: '{region}'. Must be one of: {sorted(self.KNOWN_REGIONS)}",
                violations=[f"unknown_region:{region}"],
            )
        return GuardrailResult.ok()


# ─────────────────────────────────────────────────────────────────────────────
#  Output Validator
# ─────────────────────────────────────────────────────────────────────────────

class OutputValidator:
    """Validates and sanitises AI-generated responses."""

    # PII detection patterns
    _PII_PATTERNS = [
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
         "email_address"),
        (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
         "ip_address"),
        (re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
         "openai_api_key"),
        (re.compile(r"\b(password|secret|api_key|private_key)\s*[=:]\s*\S+", re.IGNORECASE),
         "credential_in_output"),
        (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
         "credit_card_number"),
    ]

    KNOWN_RUNBOOKS = {
        "auth_service_runbook.md",
        "deployment_guide.md",
        "incident_response_sop.md",
        "matchmaking_service_runbook.md",
        "monitoring_metrics_guide.md",
        "payment_service_runbook.md",
        "player_profile_service_runbook.md",
    }

    def validate_response(
        self,
        response: dict[str, Any],
        context: dict | None = None,
    ) -> GuardrailResult:
        """Validate response structure and content."""
        violations: list[str] = []

        # Required fields
        if "answer" not in response:
            violations.append("missing_field:answer")
        if "evidence" not in response:
            violations.append("missing_field:evidence")
        if "recommended_actions" not in response:
            violations.append("missing_field:recommended_actions")

        if violations:
            return GuardrailResult.fail("Response missing required fields", violations)

        # PII check
        answer_text = str(response.get("answer", ""))
        pii_found = self.check_pii(answer_text)
        if pii_found:
            violations.extend([f"pii:{pii}" for pii in pii_found])
            logger.warning("PII detected in response: %s", pii_found)

        # Citation verification
        sources = response.get("sources", [])
        if not self.verify_citations(answer_text, sources):
            violations.append("unverified_citation")
            logger.warning("Response contains unverified citations")

        if violations:
            # For PII, block completely. For citation issues, flag but allow.
            pii_violations = [v for v in violations if v.startswith("pii:")]
            if pii_violations:
                return GuardrailResult.fail("PII detected in response", violations)

        return GuardrailResult.ok()

    def check_pii(self, text: str) -> list[str]:
        """Detect potential PII patterns in output text."""
        found: list[str] = []
        for pattern, name in self._PII_PATTERNS:
            if pattern.search(text):
                found.append(name)
        return found

    def verify_citations(self, answer: str, sources: list[dict]) -> bool:
        """Verify cited runbook files exist in the known knowledge base."""
        # Extract .md file references from the answer
        cited = re.findall(r"[\w_]+\.md", answer)
        for citation in cited:
            if citation not in self.KNOWN_RUNBOOKS:
                return False
        return True


# ─────────────────────────────────────────────────────────────────────────────
#  Rate Limiter
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """Token bucket rate limiter keyed by client identifier."""

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, client_id: str) -> GuardrailResult:
        """Check rate limits — uses Redis sliding window when available, in-memory fallback."""
        # Try Redis first (distributed, survives restarts)
        try:
            from backend.services.redis_client import rate_limit_check
            allowed, remaining = rate_limit_check(
                client_id, self._max_requests, self._window
            )
            if not allowed:
                return GuardrailResult.fail(
                    f"Rate limit exceeded. Retry after {self._window}s",
                    violations=["rate_limit_exceeded"],
                )
            return GuardrailResult.ok()
        except Exception:
            pass  # Fall through to in-memory

        # In-memory fallback
        now = time.time()
        self._cleanup(client_id, now)
        if len(self._requests[client_id]) >= self._max_requests:
            wait = self._window - (now - self._requests[client_id][0])
            return GuardrailResult.fail(
                f"Rate limit exceeded. Retry after {wait:.0f}s",
                violations=["rate_limit_exceeded"],
            )
        self._requests[client_id].append(now)
        return GuardrailResult.ok()

    def _cleanup(self, client_id: str, now: float) -> None:
        """Remove requests outside the time window."""
        cutoff = now - self._window
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > cutoff
        ]


# ─────────────────────────────────────────────────────────────────────────────
#  Circuit Breaker
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker for external service calls (LLM providers, etc.)."""

    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking calls
    HALF_OPEN = "half-open" # Testing recovery

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: int = 60,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failures: dict[str, int] = defaultdict(int)
        self._last_failure: dict[str, float] = {}
        self._state: dict[str, str] = defaultdict(lambda: self.CLOSED)

    def can_proceed(self, service: str) -> bool:
        """Check if calls to this service should proceed."""
        state = self._state[service]

        if state == self.CLOSED:
            return True

        if state == self.OPEN:
            elapsed = time.time() - self._last_failure.get(service, 0)
            if elapsed >= self._recovery_timeout:
                self._state[service] = self.HALF_OPEN
                logger.info("Circuit breaker for %s: OPEN → HALF_OPEN", service)
                return True
            return False

        if state == self.HALF_OPEN:
            return True  # Allow one test request

        return True

    def record_failure(self, service: str) -> None:
        """Record a failure and potentially open the circuit."""
        self._failures[service] += 1
        self._last_failure[service] = time.time()

        if self._failures[service] >= self._failure_threshold:
            if self._state[service] != self.OPEN:
                logger.warning(
                    "Circuit breaker for %s: OPENED after %d failures",
                    service, self._failures[service]
                )
            self._state[service] = self.OPEN

    def record_success(self, service: str) -> None:
        """Record success and reset the circuit breaker."""
        if self._state[service] == self.HALF_OPEN:
            logger.info("Circuit breaker for %s: HALF_OPEN → CLOSED", service)
        self._failures[service] = 0
        self._state[service] = self.CLOSED

    def status(self) -> dict[str, str]:
        """Return the state of all circuit breakers."""
        return dict(self._state)


# ─────────────────────────────────────────────────────────────────────────────
#  Audit Logger
# ─────────────────────────────────────────────────────────────────────────────

class AuditLogger:
    """Logs all copilot interactions for compliance and quality analysis."""

    def __init__(self) -> None:
        self._audit_logger = logging.getLogger("audit.copilot")

    def log_query(
        self,
        query: str,
        client_id: str,
        guardrail_result: GuardrailResult,
        service_name: str | None = None,
    ) -> None:
        self._audit_logger.info(
            "QUERY",
            extra={
                "event": "query_received",
                "client_id": client_id,
                "query_length": len(query),
                "query_prefix": query[:50],
                "service_name": service_name,
                "guardrail_passed": guardrail_result.passed,
                "guardrail_violations": guardrail_result.violations,
                "blocked": guardrail_result.blocked,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def log_response(
        self,
        query: str,
        response: dict[str, Any],
        guardrail_result: GuardrailResult,
        latency_ms: float = 0.0,
    ) -> None:
        self._audit_logger.info(
            "RESPONSE",
            extra={
                "event": "response_generated",
                "query_prefix": query[:50],
                "severity": response.get("severity", "N/A"),
                "risk_score": response.get("risk_score", 0.0),
                "generation_method": response.get("generation_method", "unknown"),
                "guardrail_passed": guardrail_result.passed,
                "guardrail_violations": guardrail_result.violations,
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Singletons
# ─────────────────────────────────────────────────────────────────────────────

_input_validator = InputValidator()
_output_validator = OutputValidator()
_rate_limiter = RateLimiter()
_circuit_breaker = CircuitBreaker()
_audit_logger = AuditLogger()


def validate_chat_input(
    query: str,
    service_name: str | None = None,
    region: str | None = None,
    client_id: str = "anonymous",
) -> GuardrailResult:
    """Validate chat endpoint inputs. Returns failed result if any check fails."""
    # Rate limit
    rate_result = _rate_limiter.check(client_id)
    if not rate_result.passed:
        _audit_logger.log_query(query, client_id, rate_result, service_name)
        return rate_result

    # Query validation
    query_result = _input_validator.validate_query(query)
    if not query_result.passed:
        _audit_logger.log_query(query, client_id, query_result, service_name)
        return query_result

    # Service/region validation (non-blocking — agent can infer)
    _input_validator.validate_service_name(service_name)
    _input_validator.validate_region(region)

    _audit_logger.log_query(query, client_id, query_result, service_name)
    return query_result


def validate_chat_output(
    response: dict[str, Any],
    evidence: list[str] | None = None,
    query: str = "",
) -> GuardrailResult:
    """Validate chat endpoint output. Returns failed result if guardrails trip."""
    result = _output_validator.validate_response(response)
    _audit_logger.log_response(query, response, result)
    return result


def get_circuit_breaker() -> CircuitBreaker:
    """Return the global circuit breaker instance."""
    return _circuit_breaker


# ─────────────────────────────────────────────────────────────────────────────
#  FastAPI Middleware
# ─────────────────────────────────────────────────────────────────────────────

class GuardrailsMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting and request-level guardrails to all API requests."""

    _PROTECTED_PATHS = {"/chat", "/root-cause", "/incident-summary"}

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract client identifier (IP or X-Client-ID header)
        client_id = request.headers.get(
            "X-Client-ID",
            request.client.host if request.client else "unknown",
        )

        # Rate limiting on protected paths
        if any(request.url.path.endswith(p) for p in self._PROTECTED_PATHS):
            rate_result = _rate_limiter.check(client_id)
            if not rate_result.passed:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": rate_result.reason,
                        "retry_after_seconds": 60,
                    },
                )

        response = await call_next(request)
        response.headers["X-Guardrails-Version"] = "2.0"
        return response
