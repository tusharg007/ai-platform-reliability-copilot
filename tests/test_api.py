from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_without_otel_flag(monkeypatch):
    from backend.telemetry import get_copilot_metrics
    from backend.utils.config import get_settings

    monkeypatch.setattr(get_settings(), "otel_enabled", False)
    with TestClient(app) as client:
        get_copilot_metrics().record_query(12.0, "SEV-3", "mock")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# HELP copilot_query_duration_ms" in response.text


def test_chat_payment_incident():
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "query": "Why is payment-service failing in ap-south after deployment v2.1.4?",
            "service_name": "payment-service",
            "region": "ap-south",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "payment-service" in body["answer"]
    assert body["recommended_actions"]
