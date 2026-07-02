from backend.services.anomaly_detector import AnomalyDetector


def test_payment_service_anomaly_is_flagged():
    detector = AnomalyDetector()
    anomalies = detector.detect("payment-service", "p95_latency_ms")
    assert anomalies
    assert any(item["observed_value"] >= 900 for item in anomalies)
