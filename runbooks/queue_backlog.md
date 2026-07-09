# Queue Backlog

## Symptoms
- Queue lag grows while worker throughput drops.
- Downstream notifications or async jobs are delayed.

## Investigation Steps
1. Measure consumer throughput, retries, and dead-letter activity.
2. Inspect dependency latency for jobs that now take longer to complete.
3. Check whether producers changed rate or payload size after deployment.

## Stabilization
- Increase workers temporarily if dependencies are healthy.
- Pause noisy producers or reduce retry storms.
