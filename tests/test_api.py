from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recent_incidents_endpoint():
    response = client.get("/incidents/recent")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_copilot_ask():
    response = client.post("/copilot/ask", json={"question": "Why did database-service trigger upstream timeouts?"})
    assert response.status_code == 200
    body = response.json()["response"]
    assert "Summary" in body
