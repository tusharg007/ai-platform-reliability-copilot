"""Runtime configuration for the AI Platform Reliability Copilot (production-grade)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os


# ── Filesystem Paths ──────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
KNOWLEDGE_BASE_DIR = ROOT_DIR / "knowledge_base"
VECTOR_STORE_DIR = ROOT_DIR / ".chroma"


class Settings:
    """Centralised runtime settings.

    All values are read from environment variables with sane local-dev defaults.
    In production, inject via Kubernetes Secrets / Helm values / Render env vars.
    """

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "AI Platform Reliability Copilot"
    app_version: str = "2.0.0"
    environment: str = os.getenv("APP_ENV", "local")

    # ── LLM Providers ─────────────────────────────────────────────────────────
    # LLM_PROVIDER can be "groq", "openai", "gemini", "mock" — OR a model name
    # like "gpt-oss-120b". When a model name is used, the provider is inferred
    # from whichever API key is present (GROQ_API_KEY has highest priority).
    _llm_provider_raw: str = os.getenv("LLM_PROVIDER", "mock")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    embedding_model_name: str = os.getenv(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    @property
    def llm_provider(self) -> str:
        """Resolved provider: 'groq' | 'openai' | 'gemini' | 'mock'."""
        raw = self._llm_provider_raw.lower()
        if raw in {"groq", "openai", "gemini", "mock"}:
            return raw
        # Model name supplied as provider — infer from available API keys
        if self.groq_api_key:
            return "groq"
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        return "mock"

    @property
    def resolved_model_name(self) -> str:
        """The exact model name to pass in the API call."""
        raw_lower = self._llm_provider_raw.lower()
        if raw_lower not in {"groq", "openai", "gemini", "mock"}:
            return self._llm_provider_raw  # e.g. "gpt-oss-120b"
        return self.groq_model             # e.g. "llama-3.1-8b-instant"

    # ── Database ──────────────────────────────────────────────────────────────
    # Dev default: SQLite via aiosqlite (zero-config).
    # Production: set DATABASE_URL=postgresql+asyncpg://user:pass@host/db
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{DATA_DIR / 'platform_reliability.db'}",
    )
    db_pool_min: int = int(os.getenv("DB_POOL_MIN", "2"))
    db_pool_max: int = int(os.getenv("DB_POOL_MAX", "10"))

    # ── Cache / Pub-Sub ───────────────────────────────────────────────────────
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_enabled: bool = os.getenv("REDIS_ENABLED", "false").lower() == "true"

    # ── Streaming (optional Kafka) ────────────────────────────────────────────
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_enabled: bool = os.getenv("KAFKA_ENABLED", "false").lower() == "true"

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    otel_enabled: bool = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "reliability-copilot")
    otel_exporter_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format: str = os.getenv("LOG_FORMAT", "json")  # "json" | "console"

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expiry_minutes: int = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))
    auth_enabled: bool = os.getenv("AUTH_ENABLED", "false").lower() == "true"

    # ── Risk Scoring Weights ──────────────────────────────────────────────────
    # Weights must sum to 1.0.  Override via JSON env var RISK_SCORE_WEIGHTS.
    risk_score_weights: dict = {
        "blast_radius": float(os.getenv("RISK_W_BLAST_RADIUS", "0.25")),
        "velocity": float(os.getenv("RISK_W_VELOCITY", "0.20")),
        "slo_burn": float(os.getenv("RISK_W_SLO_BURN", "0.25")),
        "historical": float(os.getenv("RISK_W_HISTORICAL", "0.15")),
        "revenue": float(os.getenv("RISK_W_REVENUE", "0.15")),
    }

    # ── Anomaly Detection ─────────────────────────────────────────────────────
    anomaly_cooldown_seconds: int = int(os.getenv("ANOMALY_COOLDOWN_SECONDS", "300"))
    anomaly_z_threshold_default: float = float(os.getenv("ANOMALY_Z_THRESHOLD", "3.0"))
    anomaly_z_threshold_error_rate: float = float(os.getenv("ANOMALY_Z_THRESHOLD_ERROR_RATE", "2.5"))

    # ── Eval / Guardrail Thresholds ───────────────────────────────────────────
    eval_groundedness_threshold: float = float(os.getenv("EVAL_GROUNDEDNESS_THRESHOLD", "0.95"))
    eval_hallucination_threshold: float = float(os.getenv("EVAL_HALLUCINATION_THRESHOLD", "0.02"))
    eval_relevance_threshold: float = float(os.getenv("EVAL_RELEVANCE_THRESHOLD", "0.90"))

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

    # ── SLO Configuration ─────────────────────────────────────────────────────
    slo_availability_target: float = float(os.getenv("SLO_AVAILABILITY_TARGET", "0.999"))  # 99.9%
    slo_latency_p95_ms: float = float(os.getenv("SLO_LATENCY_P95_MS", "500.0"))

    # ── Alert Routing ─────────────────────────────────────────────────────────
    slack_webhook_url: str | None = os.getenv("SLACK_WEBHOOK_URL")
    pagerduty_routing_key: str | None = os.getenv("PAGERDUTY_ROUTING_KEY")
    alert_min_severity: str = os.getenv("ALERT_MIN_SEVERITY", "SEV-2")


@lru_cache
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()
