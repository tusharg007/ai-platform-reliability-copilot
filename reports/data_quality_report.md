# Data Quality Report

This report reflects generated synthetic platform telemetry after ingestion and normalization.

## Summary
- Records analyzed: 28224
- Hourly metric rows: 2352
- Timestamp range: 2026-06-25 21:00:00+00:00 to 2026-07-09 20:55:00+00:00
- Duplicate request IDs: 0

## Missing Values
- timestamp: 0
- service_name: 0
- environment: 0
- log_level: 0
- request_id: 0
- trace_id: 0
- endpoint: 0
- status_code: 0
- latency_ms: 0
- error_type: 0
- message: 0
- cpu_usage: 0
- memory_usage: 0
- db_latency_ms: 0
- queue_lag: 0
- region: 0
- deployment_version: 0
- hour: 0
- is_error: 0
- is_auth_failure: 0
- is_timeout: 0

## Log Level Distribution
- INFO: 99.50%
- ERROR: 0.30%
- WARN: 0.20%

## Service Coverage
- api-gateway: 4032 rows
- auth-service: 4032 rows
- database-service: 4032 rows
- notification-service: 4032 rows
- payment-service: 4032 rows
- recommendation-service: 4032 rows
- worker-service: 4032 rows

## Error Rate By Service
- payment-service: 0.84%
- api-gateway: 0.50%
- notification-service: 0.22%
- recommendation-service: 0.20%
- worker-service: 0.20%
- database-service: 0.12%
- auth-service: 0.00%
