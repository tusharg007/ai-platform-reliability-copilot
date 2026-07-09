# Sample Copilot Responses

These examples are generated from synthetic telemetry and retrieved runbooks.

## Prompt: Why did database-service trigger upstream timeouts?

### Summary
database-service is currently classified as Medium risk with a score of 40.41. Recent windows show elevated reliability pressure consistent with database timeout or downstream query latency. This is a production-oriented prototype using synthetic platform logs and simulated incidents.

### Likely cause
database timeout or downstream query latency

### Supporting evidence
- Risk score: 40.41
- Risk band: Medium
- 24h error rate: 0.47%
- P95 latency: 68.3 ms
- Recent high/critical alert count: 0
- Top risk drivers: memory pressure, error rate, CPU pressure
- Related incidents: INC-CLUSTER-088, INC-CLUSTER-050
- Recent alert types: db_latency_spike, latency_spike
- INC-2001 - database timeout
- database_timeout.md
- INC-2006 - queue backlog

### Similar incidents/runbooks
- known_incident: INC-2001 - database timeout
- runbook: database_timeout.md
- known_incident: INC-2006 - queue backlog

### Recommended next debugging steps
- Inspect slow queries, connection pool saturation, and timeout budgets.
- Compare affected deployment versions and rollback criteria.
- Trace which upstream services inherit the timeout behavior.

### Human review note
Validate the hypothesis against live traces, deployment notes, and on-call context before acting.

## Prompt: Summarize INC-CLUSTER-001

### Summary
api-gateway is currently classified as High risk with a score of 67.48. Recent windows show elevated reliability pressure consistent with 5xx error spike. This is a production-oriented prototype using synthetic platform logs and simulated incidents.

### Likely cause
5xx error spike

### Supporting evidence
- Risk score: 67.48
- Risk band: High
- 24h error rate: 1.10%
- P95 latency: 140.7 ms
- Recent high/critical alert count: 6
- Top risk drivers: error rate, anomaly count, incident count
- Related incidents: INC-CLUSTER-086, INC-CLUSTER-035, INC-CLUSTER-034
- Recent alert types: external_api_failure, error_rate_spike, auth_failure_spike, latency_spike
- 5 alerts across 3 services from 2026-06-26T22:00:00+00:00 to 2026-06-27T06:00:00+00:00. Dominant symptoms: error_rate_spike. Deployment context: 2026.07.1.
- Affected services: api-gateway, auth-service, payment-service. Severity: high.
- INC-CLUSTER-001 - 5xx error spike
- INC-CLUSTER-052 - external API failure
- INC-CLUSTER-002 - 5xx error spike

### Similar incidents/runbooks
- predicted_incident: INC-CLUSTER-001 - 5xx error spike
- predicted_incident: INC-CLUSTER-052 - external API failure
- predicted_incident: INC-CLUSTER-002 - 5xx error spike

### Recommended next debugging steps
- Correlate anomalies with recent releases, traffic shifts, and dependency health.
- Inspect high-severity logs and representative traces from the incident window.
- Have an engineer verify the recommendation before mitigation.

### Human review note
Validate the hypothesis against live traces, deployment notes, and on-call context before acting.
