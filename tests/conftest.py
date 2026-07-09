from src.detect_anomalies import detect_anomalies
from src.evaluate_system import evaluate_system
from src.generate_synthetic_logs import generate_synthetic_logs
from src.incident_clustering import cluster_incidents
from src.ingest_logs import ingest_logs
from src.service_risk_scoring import score_services
from src.capture_screenshots import capture_screenshots
from src.validate_outputs import validate_outputs


def pytest_sessionstart(session):
    generate_synthetic_logs(quick=True)
    ingest_logs()
    detect_anomalies()
    cluster_incidents()
    score_services()
    evaluate_system()
    capture_screenshots()
    validate_outputs()
