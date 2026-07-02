from backend.services.incident_generator import IncidentGenerator


def test_incident_generator_returns_summary():
    result = IncidentGenerator().full_incident("payment-service", "ap-south")
    assert "payment-service" in result["summary"]
    assert result["action_plan"]
