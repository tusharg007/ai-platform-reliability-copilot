from backend.services.log_analyzer import LogAnalyzer


def test_log_analyzer_calculates_error_rate():
    analyzer = LogAnalyzer()
    rate = analyzer.calculate_error_rate("payment-service", "ap-south")
    assert rate > 0.04
