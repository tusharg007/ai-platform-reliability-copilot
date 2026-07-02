from fastapi import APIRouter

from backend.models.schemas import LogAnalysisResponse, ServiceRegionRequest
from backend.services.log_analyzer import LogAnalyzer


router = APIRouter()


@router.post("/analyze-logs", response_model=LogAnalysisResponse)
def analyze_logs(request: ServiceRegionRequest) -> LogAnalysisResponse:
    analyzer = LogAnalyzer()
    errors = analyzer.summarize_errors(request.service_name, request.region)
    return LogAnalysisResponse(
        service_name=request.service_name,
        region=request.region,
        total_logs=errors["total_logs"],
        error_rate=errors["error_rate"],
        top_error_types=errors["top_errors"],
        latency_summary=analyzer.calculate_latency_summary(request.service_name, request.region),
        deployment_failures=analyzer.identify_deployment_related_failures(request.service_name),
    )
