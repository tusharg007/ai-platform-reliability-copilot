# Payment Service Runbook

## Overview
The payment-service authorizes purchases, wallet updates, refund events, and transaction state transitions for live game commerce systems.

## Common symptoms
- Elevated 503 or 504 responses from checkout and wallet APIs.
- P95 latency rising above 800 ms for more than 10 minutes.
- DB_CONNECTION_TIMEOUT errors clustered in one region.
- Error rate above 5 percent after a deployment.

## Key metrics to check
- Error rate by region and deployment version.
- P95 latency and timeout count.
- Database connection pool utilization.
- Slow query count and lock wait time.
- Downstream payment provider latency.

## Common root causes
- Database connection pool saturation after a deployment.
- Schema migration creating slow queries or lock contention.
- Payment provider timeout or throttling.
- Retry storms caused by client or gateway behavior.

## Debugging steps
1. Compare the current deployment version against the last stable release.
2. Segment error rate and p95 latency by region.
3. Search logs for DB_CONNECTION_TIMEOUT and provider timeout messages.
4. Inspect database connection pool saturation and slow query dashboards.
5. Check whether retry volume increased after the deployment.

## Recommended fixes
- Increase connection pool limits only after confirming database capacity.
- Roll back the deployment if error rate remains above 5 percent for 15 minutes.
- Disable aggressive retries if they are amplifying database pressure.
- Add circuit breaking around payment provider calls.

## Escalation criteria
Escalate to SEV-2 when payment authorization failures affect a production region for more than 10 minutes or revenue-impacting checkout requests exceed a 5 percent error rate.
