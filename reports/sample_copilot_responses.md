# Sample Copilot Responses

These examples are generated from synthetic telemetry and retrieved runbooks.

## Prompt: Why did database-service trigger upstream timeouts?

### Summary
The current signal points to database timeout or downstream query latency. This is a production-oriented prototype using synthetic platform logs and simulated incidents.

### Likely cause
database timeout or downstream query latency

### Supporting evidence
- INC-1001 - database timeout
- database_timeout.md
- INC-1004 - queue backlog

### Similar incidents/runbooks
- known_incident: INC-1001 - database timeout
- runbook: database_timeout.md
- known_incident: INC-1004 - queue backlog

### Recommended next debugging steps
- Inspect slow queries, connection pool saturation, and timeout budgets.
- Compare affected deployment versions and rollback criteria.
- Trace which upstream services inherit the timeout behavior.

### Human review note
Validate the hypothesis against live traces, deployment notes, and on-call context before acting.

## Prompt: Summarize INC-CLUSTER-001

### Summary
The current signal points to generic_anomaly. This is a production-oriented prototype using synthetic platform logs and simulated incidents.

### Likely cause
generic_anomaly

### Supporting evidence
- Peak p95 latency 144.3 ms, peak error rate 0.00%, peak queue lag 4.3, peak DB latency 39.0 ms.
- Affected services: api-gateway. Severity: medium.
- INC-CLUSTER-001 - generic_anomaly
- INC-CLUSTER-149 - generic_anomaly
- INC-CLUSTER-125 - generic_anomaly

### Similar incidents/runbooks
- predicted_incident: INC-CLUSTER-001 - generic_anomaly
- predicted_incident: INC-CLUSTER-149 - generic_anomaly
- predicted_incident: INC-CLUSTER-125 - generic_anomaly

### Recommended next debugging steps
- Correlate anomalies with recent releases, traffic shifts, and dependency health.
- Inspect high-severity logs and representative traces from the incident window.
- Have an engineer verify the recommendation before mitigation.

### Human review note
Validate the hypothesis against live traces, deployment notes, and on-call context before acting.
