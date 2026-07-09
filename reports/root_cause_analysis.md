# Root Cause Analysis

The calibrated synthetic scenarios generate distinct patterns such as deployment regressions, queue backlog, database timeout propagation, external provider failures, and auth spikes.

## Incident Samples
- INC-CLUSTER-001: payment-service | 5xx error spike | critical | alerts=7
- INC-CLUSTER-049: payment-service | external API failure | critical | alerts=7
- INC-CLUSTER-002: payment-service | 5xx error spike | high | alerts=1
- INC-CLUSTER-050: payment-service | external API failure | high | alerts=1
- INC-CLUSTER-028: auth-service | authentication failure spike | medium | alerts=1
- INC-CLUSTER-051: auth-service | external API failure | critical | alerts=1
- INC-CLUSTER-003: auth-service | 5xx error spike | critical | alerts=1
- INC-CLUSTER-004: api-gateway | 5xx error spike | critical | alerts=3
