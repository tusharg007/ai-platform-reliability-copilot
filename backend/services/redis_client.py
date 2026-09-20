"""Redis client singleton with graceful fallback.

When REDIS_ENABLED=true, provides:
  - Caching for RAG results, risk scores, anomaly results
  - Distributed rate limiting (replacing in-memory token bucket)
  - Session memory persistence (replacing in-memory dict)
  - Pub/Sub for real-time alert fanout

When Redis is unavailable (connection refused, timeout), every operation
degrades silently to a no-op or returns None — the system never crashes
due to a missing cache layer.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_client = None
_available = False
_checked_at: float = 0.0
_RECHECK_INTERVAL = 30.0  # Re-probe connection every 30 s after a failure


def _build_client():
    """Build a Redis client from config. Returns None if Redis is disabled."""
    from backend.utils.config import get_settings
    settings = get_settings()

    if not settings.redis_enabled:
        return None

    try:
        import redis
        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )
        client.ping()  # Verify connection now
        logger.info("Redis connected: %s", settings.redis_url)
        return client
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — running without cache", exc)
        return None


def get_client():
    """Return the Redis client, or None if Redis is disabled / unreachable."""
    global _client, _available, _checked_at

    # Already confirmed available
    if _client is not None and _available:
        return _client

    # Throttle reconnection attempts
    now = time.monotonic()
    if not _available and (now - _checked_at) < _RECHECK_INTERVAL:
        return None

    _checked_at = now
    _client = _build_client()
    _available = _client is not None
    return _client


def is_available() -> bool:
    """Return True if Redis is connected and responsive."""
    client = get_client()
    if client is None:
        return False
    try:
        client.ping()
        return True
    except Exception:
        global _available
        _available = False
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Cache Helpers
# ─────────────────────────────────────────────────────────────────────────────

def cache_get(key: str) -> Any | None:
    """Get a JSON-serialised value from Redis. Returns None on miss or error."""
    client = get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.debug("Redis GET failed for key=%s: %s", key, exc)
        return None


def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Set a JSON-serialised value in Redis with TTL. Returns True on success."""
    client = get_client()
    if client is None:
        return False
    try:
        client.setex(key, ttl_seconds, json.dumps(value, default=str))
        return True
    except Exception as exc:
        logger.debug("Redis SET failed for key=%s: %s", key, exc)
        return False


def cache_delete(key: str) -> None:
    """Delete a key from Redis."""
    client = get_client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Distributed Rate Limiter (sliding window via Redis ZADD)
# ─────────────────────────────────────────────────────────────────────────────

def rate_limit_check(
    client_id: str,
    max_requests: int = 60,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """Sliding window rate limiter using Redis sorted sets.

    Returns:
        (allowed: bool, remaining: int)
    """
    client = get_client()
    if client is None:
        return True, max_requests  # No Redis → allow all

    key = f"ratelimit:{client_id}"
    now = time.time()
    window_start = now - window_seconds

    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)       # Drop old entries
        pipe.zadd(key, {str(now): now})                   # Add current request
        pipe.zcard(key)                                   # Count requests in window
        pipe.expire(key, window_seconds + 1)              # TTL cleanup
        results = pipe.execute()

        count = results[2]
        allowed = count <= max_requests
        remaining = max(0, max_requests - count)
        return allowed, remaining
    except Exception as exc:
        logger.debug("Redis rate limit check failed: %s", exc)
        return True, max_requests  # Fail open


# ─────────────────────────────────────────────────────────────────────────────
#  Session Memory Store
# ─────────────────────────────────────────────────────────────────────────────

def session_get(session_id: str) -> list[dict] | None:
    """Retrieve conversation history for a session from Redis."""
    return cache_get(f"session:{session_id}")


def session_set(session_id: str, turns: list[dict], ttl_seconds: int = 3600) -> None:
    """Persist conversation history for a session to Redis."""
    cache_set(f"session:{session_id}", turns, ttl_seconds)


# ─────────────────────────────────────────────────────────────────────────────
#  Health Info
# ─────────────────────────────────────────────────────────────────────────────

def redis_info() -> dict:
    """Return Redis connection info for /pipeline/status endpoint."""
    from backend.utils.config import get_settings
    settings = get_settings()

    if not settings.redis_enabled:
        return {"enabled": False, "status": "disabled"}

    client = get_client()
    if client is None:
        return {"enabled": True, "status": "unavailable"}

    try:
        info = client.info("server")
        return {
            "enabled": True,
            "status": "connected",
            "version": info.get("redis_version", "unknown"),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
            "url": settings.redis_url.split("@")[-1],  # hide credentials
        }
    except Exception as exc:
        return {"enabled": True, "status": f"error: {exc}"}
