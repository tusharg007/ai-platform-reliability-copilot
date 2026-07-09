# Data Quality Report

Synthetic platform telemetry was normalized into service-level hourly metrics with incident flags.

## Summary
- Raw log rows: 14329
- Hourly metric rows: 504
- Timestamp range: 2026-07-06 23:00:27+00:00 to 2026-07-09 22:59:44+00:00
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
- payment-service: 2.27%
- api-gateway: 1.40%
- worker-service: 1.00%
- notification-service: 0.57%
- recommendation-service: 0.40%
- auth-service: 0.34%
- database-service: 0.27%

## Request Count Variation
- api-gateway: min=38.0, mean=61.64, max=88.0
- auth-service: min=25.0, mean=41.44, max=63.0
- database-service: min=12.0, mean=15.65, max=22.0
- notification-service: min=12.0, mean=17.12, max=23.0
- payment-service: min=13.0, mean=21.44, max=32.0
- recommendation-service: min=17.0, mean=27.83, max=39.0
- worker-service: min=12.0, mean=13.88, max=19.0

## Incident Coverage
- Incident-flagged service-hour rows: 45
- Distinct incident labels: 4
