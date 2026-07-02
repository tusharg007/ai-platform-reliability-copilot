from fastapi import APIRouter

from backend.models.schemas import FeedbackRequest, IncidentResponse, ServiceRegionRequest
from backend.services.incident_generator import IncidentGenerator


router = APIRouter()


@router.post("/incident-summary", response_model=IncidentResponse)
def incident_summary(request: ServiceRegionRequest) -> IncidentResponse:
    generator = IncidentGenerator()
    incident = generator.full_incident(request.service_name, request.region)
    return IncidentResponse(service_name=request.service_name, region=request.region, **incident)


@router.post("/feedback")
def feedback(request: FeedbackRequest) -> dict:
    return {"status": "received", "rating": request.rating}
