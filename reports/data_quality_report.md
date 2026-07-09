# Data Quality Report

Synthetic platform telemetry was normalized into service-level hourly metrics with incident flags.

## Summary
- Raw log rows: 166199
- Hourly metric rows: 2352
- Timestamp range: 2026-06-25 21:00:01+00:00 to 2026-07-09 20:59:56+00:00
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
- payment-service: 1.70%
- api-gateway: 1.58%
- notification-service: 0.93%
- worker-service: 0.75%
- recommendation-service: 0.72%
- database-service: 0.59%
- auth-service: 0.46%

## Request Count Variation
- api-gateway: min=82.0, mean=155.97, max=240.0
- auth-service: min=50.0, mean=103.21, max=153.0
- database-service: min=20.0, mean=38.54, max=62.0
- notification-service: min=21.0, mean=42.26, max=64.0
- payment-service: min=27.0, mean=53.69, max=85.0
- recommendation-service: min=38.0, mean=69.04, max=110.0
- worker-service: min=17.0, mean=31.92, max=50.0

## Incident Coverage
- Incident-flagged service-hour rows: 112
- Distinct incident labels: 7
