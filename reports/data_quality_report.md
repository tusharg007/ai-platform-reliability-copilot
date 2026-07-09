# Data Quality Report

Synthetic platform telemetry was normalized into service-level hourly metrics with incident flags.

## Summary
- Raw log rows: 166542
- Hourly metric rows: 2352
- Timestamp range: 2026-06-25 22:00:07+00:00 to 2026-07-09 21:59:33+00:00
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
- is_4xx: 0
- is_5xx: 0
- is_auth_failure: 0
- known_incident_flag: 0
- incident_label: 0

## Error Rate By Service
- api-gateway: 1.63%
- payment-service: 1.63%
- notification-service: 0.94%
- worker-service: 0.91%
- database-service: 0.71%
- recommendation-service: 0.70%
- auth-service: 0.48%

## Request Count Variation
- api-gateway: min=85.0, mean=155.86, max=241.0
- auth-service: min=54.0, mean=103.64, max=160.0
- database-service: min=21.0, mean=38.52, max=60.0
- notification-service: min=22.0, mean=42.25, max=64.0
- payment-service: min=28.0, mean=53.8, max=83.0
- recommendation-service: min=36.0, mean=69.76, max=110.0
- worker-service: min=16.0, mean=31.84, max=49.0

## Incident Coverage
- Incident-flagged service-hour rows: 112
- Distinct incident labels: 7
