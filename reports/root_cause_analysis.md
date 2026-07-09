# Root Cause Analysis

The calibrated synthetic scenarios generate distinct patterns such as deployment regressions, queue backlog, database timeout propagation, external provider failures, and auth spikes.

## Incident Samples
- INC-CLUSTER-001: api-gateway | 5xx error spike | high | alerts=1
- INC-CLUSTER-007: api-gateway | external API failure | high | alerts=1
- INC-CLUSTER-002: payment-service | external API failure | high | alerts=3
- INC-CLUSTER-004: auth-service | authentication failure spike | medium | alerts=1
- INC-CLUSTER-008: payment-service | external API failure | high | alerts=3
- INC-CLUSTER-010: payment-service | external API failure | high | alerts=1
- INC-CLUSTER-011: notification-service | queue backlog | critical | alerts=11
- INC-CLUSTER-012: worker-service | queue backlog | critical | alerts=6
