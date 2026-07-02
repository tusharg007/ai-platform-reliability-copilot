from fastapi import APIRouter

from backend.models.schemas import AnomalyRequest, AnomalyResponse
from backend.services.anomaly_detector import AnomalyDetector
from backend.services.log_analyzer import LogAnalyzer


router = APIRouter()


@router.get("/metrics/summary")
def metrics_summary() -> dict:
    return LogAnalyzer().metrics_summary()


@router.post("/detect-anomalies", response_model=AnomalyResponse)
def detect_anomalies(request: AnomalyRequest) -> AnomalyResponse:
    detector = AnomalyDetector()
    return AnomalyResponse(
        service_name=request.service_name,
        health_score=detector.get_service_health_score(request.service_name, request.region),
        anomalies=detector.detect(request.service_name, request.metric_name, request.region),
    )
