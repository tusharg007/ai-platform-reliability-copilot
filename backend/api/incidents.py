"""Production incidents API: incident summary, postmortem, and feedback."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter

from backend.models.schemas import FeedbackRequest, IncidentResponse, ServiceRegionRequest
from backend.services.incident_generator import IncidentGenerator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/incident-summary", response_model=IncidentResponse)
def incident_summary(request: ServiceRegionRequest) -> IncidentResponse:
    """Generate a full incident summary, root-cause hypothesis, and postmortem template."""
    generator = IncidentGenerator()
    incident = generator.full_incident(request.service_name, request.region)
    return IncidentResponse(
        service_name=request.service_name,
        region=request.region,
        **incident,
    )


@router.post("/feedback")
def feedback(request: FeedbackRequest) -> dict:
    """Record user feedback on a copilot response.

    In production, persists to the user_feedback table for quality analysis
    and RLHF-style improvement tracking.
    """
    logger.info(
        "Feedback received: rating=%d service=%s session=%s",
        request.rating,
        request.service_name or "unknown",
        request.session_id or "anonymous",
    )
    return {
        "status": "received",
        "rating": request.rating,
        "recorded_at": datetime.utcnow().isoformat(),
    }
