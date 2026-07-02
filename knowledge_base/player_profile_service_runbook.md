# Player Profile Service Runbook

## Overview
The player-profile-service owns player metadata, preferences, inventory summaries, and profile reads used across gameplay systems.

## Common symptoms
- Elevated read latency.
- Cache miss storms.
- Profile update conflicts.
- Increased 500 responses during inventory refreshes.

## Key metrics to check
- Cache hit ratio.
- Database read/write latency.
- Conflict and retry count.
- Regional request volume.

## Common root causes
- Hot partitions for popular player cohorts.
- Cache invalidation errors.
- Inventory event replay backlog.
- Database read replica lag.

## Debugging steps
1. Check whether read or write paths are failing.
2. Inspect cache hit ratio and replica lag.
3. Search logs for conflict retries and stale profile reads.
4. Compare traffic by region and cohort.

## Recommended fixes
- Warm high-traffic cache keys.
- Route reads away from lagging replicas.
- Backpressure inventory refresh jobs.
- Patch invalid cache key construction.

## Escalation criteria
Escalate when profile reads block login or game-session creation for more than 10 minutes.
