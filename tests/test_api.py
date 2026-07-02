from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
