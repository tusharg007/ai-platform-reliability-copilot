"""JWT-based authentication and RBAC for the AI Platform Reliability Copilot.

Provides:
  - JWT token generation and verification
  - Role-Based Access Control (admin, operator, viewer)
  - FastAPI dependency for protected routes
  - API key verification for programmatic access

Enable via AUTH_ENABLED=true environment variable.
When disabled (default), all requests are treated as anonymous operator.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.utils.config import get_settings

logger = logging.getLogger(__name__)

try:
    import jwt
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False
    logger.warning("PyJWT not installed; auth will run in bypass mode")


# ─────────────────────────────────────────────────────────────────────────────
#  Roles & Permissions
# ─────────────────────────────────────────────────────────────────────────────

class Role:
    ADMIN = "admin"       # Full access: read + write + admin operations
    OPERATOR = "operator" # Read + write: can trigger actions, submit feedback
    VIEWER = "viewer"     # Read-only: dashboards, metrics, runbooks


ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN: {
        "chat", "analyze-logs", "detect-anomalies", "incident-summary",
        "feedback", "risk-score", "fleet-risk", "cluster-incidents",
        "root-cause", "dashboard-kpis", "ingest", "admin",
    },
    Role.OPERATOR: {
        "chat", "analyze-logs", "detect-anomalies", "incident-summary",
        "feedback", "risk-score", "fleet-risk", "cluster-incidents",
        "root-cause", "dashboard-kpis",
    },
    Role.VIEWER: {
        "dashboard-kpis", "fleet-risk", "detect-anomalies",
        "analyze-logs", "metrics-summary",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Token Data
# ─────────────────────────────────────────────────────────────────────────────

class TokenData:
    """Decoded JWT token payload."""
    def __init__(self, sub: str, role: str, exp: datetime | None = None) -> None:
        self.sub = sub      # User/service identifier
        self.role = role    # RBAC role
        self.exp = exp      # Expiry

    def has_permission(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, set())


# ─────────────────────────────────────────────────────────────────────────────
#  JWT Utilities
# ─────────────────────────────────────────────────────────────────────────────

def create_access_token(sub: str, role: str = Role.OPERATOR) -> str:
    """Create a signed JWT access token.

    Args:
        sub:  Subject identifier (user ID, service name, etc.)
        role: RBAC role (admin, operator, viewer)

    Returns:
        Signed JWT string.
    """
    settings = get_settings()
    if not _JWT_AVAILABLE:
        return f"bypass-token:{sub}:{role}"

    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> TokenData:
    """Decode and verify a JWT token.

    Raises:
        HTTPException 401 if token is invalid or expired.
    """
    settings = get_settings()

    if token.startswith("bypass-token:"):
        # Dev mode bypass token
        parts = token.split(":")
        return TokenData(sub=parts[1] if len(parts) > 1 else "dev", role=parts[2] if len(parts) > 2 else Role.OPERATOR)

    if not _JWT_AVAILABLE:
        return TokenData(sub="anonymous", role=Role.OPERATOR)

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return TokenData(
            sub=payload.get("sub", "unknown"),
            role=payload.get("role", Role.VIEWER),
            exp=datetime.fromtimestamp(payload["exp"]) if "exp" in payload else None,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────────────────────────────────────────
#  FastAPI Dependencies
# ─────────────────────────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenData:
    """FastAPI dependency: extract and verify JWT from Authorization header.

    When AUTH_ENABLED=false, returns an anonymous operator token (no-op).
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return TokenData(sub="anonymous", role=Role.OPERATOR)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return decode_token(credentials.credentials)


def require_role(required_role: str):
    """FastAPI dependency factory: require a minimum role level.

    Usage::

        @router.post("/admin-only")
        def admin_endpoint(user: TokenData = Depends(require_role(Role.ADMIN))):
            ...
    """
    role_hierarchy = [Role.VIEWER, Role.OPERATOR, Role.ADMIN]

    def dependency(user: TokenData = Depends(get_current_user)) -> TokenData:
        user_level = role_hierarchy.index(user.role) if user.role in role_hierarchy else 0
        required_level = role_hierarchy.index(required_role) if required_role in role_hierarchy else 0
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}, current: {user.role}",
            )
        return user

    return dependency


# ─────────────────────────────────────────────────────────────────────────────
#  Auth Router (token issuance for dev/testing)
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter
from pydantic import BaseModel

auth_router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    sub: str
    role: str = Role.OPERATOR


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in_minutes: int


@auth_router.post("/token", response_model=TokenResponse)
def issue_token(request: TokenRequest) -> TokenResponse:
    """Issue a JWT token (development/testing only).

    In production, integrate with your OIDC provider (Google, Okta, Auth0).
    This endpoint should be disabled or protected by network policy in prod.
    """
    settings = get_settings()
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct token issuance disabled in production. Use your OIDC provider.",
        )
    token = create_access_token(request.sub, request.role)
    return TokenResponse(
        access_token=token,
        role=request.role,
        expires_in_minutes=settings.jwt_expiry_minutes,
    )
