# Root Cause Analysis

The calibrated synthetic scenarios generate distinct patterns such as deployment regressions, queue backlog, database timeout propagation, external provider failures, and auth spikes.

## Incident Samples
- INC-CLUSTER-042: auth-service | authentication failure spike | high | alerts=1
- INC-CLUSTER-061: auth-service | external API failure | high | alerts=2
- INC-CLUSTER-001: auth-service | 5xx error spike | high | alerts=2
- INC-CLUSTER-002: api-gateway | 5xx error spike | low | alerts=2
- INC-CLUSTER-062: api-gateway | external API failure | medium | alerts=2
- INC-CLUSTER-043: auth-service | authentication failure spike | high | alerts=1
- INC-CLUSTER-003: api-gateway | 5xx error spike | high | alerts=5
- INC-CLUSTER-063: api-gateway | external API failure | high | alerts=5
