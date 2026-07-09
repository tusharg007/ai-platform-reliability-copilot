# High Latency

## Symptoms
- p95 latency rises while success rates may remain mostly intact.
- CPU saturation, fan-out dependencies, or noisy neighbors can contribute.

## Investigation Steps
1. Identify whether the spike is CPU, DB, or dependency driven.
2. Compare top slow endpoints and recent deployments.
3. Trace representative slow requests.

## Stabilization
- Shift traffic or roll back the latest release if correlated.
- Reduce expensive request paths and batch sizes.
