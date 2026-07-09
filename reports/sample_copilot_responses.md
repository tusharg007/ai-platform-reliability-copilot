# Sample Copilot Responses

These examples are generated from synthetic telemetry and retrieved runbooks.

## Prompt: Why did database-service trigger upstream timeouts?

### Summary
The current signal points to database timeout or downstream query latency. This is a production-oriented prototype using synthetic platform logs and simulated incidents.

### Likely cause
database timeout or downstream query latency

### Supporting evidence
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
The current signal points to 5xx error spike. This is a production-oriented prototype using synthetic platform logs and simulated incidents.

### Likely cause
5xx error spike

### Supporting evidence
- 7 alerts across 3 services from 2026-06-26T23:00:00+00:00 to 2026-06-27T04:00:00+00:00. Dominant symptoms: error_rate_spike. Deployment context: 2026.07.1.
- Affected services: api-gateway, auth-service, payment-service. Severity: critical.
- INC-CLUSTER-001 - 5xx error spike
- INC-CLUSTER-049 - external API failure
- INC-CLUSTER-004 - 5xx error spike

### Similar incidents/runbooks
- predicted_incident: INC-CLUSTER-001 - 5xx error spike
- predicted_incident: INC-CLUSTER-049 - external API failure
- predicted_incident: INC-CLUSTER-004 - 5xx error spike

### Recommended next debugging steps
- Correlate anomalies with recent releases, traffic shifts, and dependency health.
- Inspect high-severity logs and representative traces from the incident window.
- Have an engineer verify the recommendation before mitigation.

### Human review note
Validate the hypothesis against live traces, deployment notes, and on-call context before acting.
