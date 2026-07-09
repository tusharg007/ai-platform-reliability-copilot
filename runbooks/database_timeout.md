# Database Timeout

## Symptoms
- Elevated database latency and repeated timeout errors.
- Upstream services show 504s and retry amplification.

## Likely Causes
- Slow queries or lock contention.
- Connection pool saturation after a deployment.
- Hot partitions or synthetic traffic bursts.

## Investigation Steps
1. Inspect slow query patterns and connection counts.
2. Compare the latest deployment version against the last stable release.
3. Check which upstream services are inheriting timeout behavior.

## Stabilization
- Reduce retry pressure.
- Roll back the offending release if the regression is deployment-correlated.
- Scale or tune the connection pool only after validating database health.
