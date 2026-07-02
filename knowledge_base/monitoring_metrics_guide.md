# Monitoring Metrics Guide

## Overview
Reliability triage depends on connecting metrics to logs, deployments, regions, and runbooks.

## Common symptoms
- Error rate, latency, or timeout count changes faster than traffic.
- CPU and memory rise alongside p95 latency.
- Request volume changes hide regional failures.
- Alert noise lacks root-cause context.

## Key metrics to check
- P50, P95, and P99 latency.
- Error rate by status code and error type.
- Timeout count.
- CPU and memory utilization.
- Request count by service and region.
- Deployment version.

## Common root causes
- Dependency saturation.
- Deployment regression.
- Autoscaling lag.
- Region-specific networking or capacity issues.

## Debugging steps
1. Compare current values to rolling baseline.
2. Segment metrics by service, region, and deployment version.
3. Correlate metric anomalies with log error types.
4. Verify whether recovery follows rollback or scaling.

## Recommended fixes
- Add alerts on rolling z-score, not only fixed thresholds.
- Include deployment version in every log and metric row.
- Track timeout count as an early signal for dependency failures.
- Keep dashboards service-oriented and incident-ready.

## Escalation criteria
Escalate when multiple metrics breach SLO and a single owner cannot explain the degradation.
