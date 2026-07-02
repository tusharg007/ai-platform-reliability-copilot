# Auth Service Runbook

## Overview
The auth-service validates identity tokens, session refreshes, and service-to-service credentials.

## Common symptoms
- Spikes in 401, 403, 503, or gateway timeout responses.
- Token validation latency above 500 ms.
- Cache miss storms against identity metadata.
- AUTH_TOKEN_EXPIRED or JWKS_REFRESH_FAILED log messages.

## Key metrics to check
- Token validation latency.
- Identity provider latency and error rate.
- Cache hit ratio for signing keys.
- Request volume by client application.

## Common root causes
- Expired signing keys or failed JWKS refresh.
- Identity provider degradation.
- Redis/cache eviction causing repeated metadata fetches.
- Misconfigured rollout of auth middleware.

## Debugging steps
1. Confirm whether failures are user-facing or internal service calls.
2. Check token validation latency and cache hit rate.
3. Search logs for AUTH_TOKEN_EXPIRED and JWKS_REFRESH_FAILED.
4. Verify recent deployments changed token parsing, scopes, or middleware.

## Recommended fixes
- Refresh signing key cache.
- Revert auth middleware changes if failures started after deployment.
- Apply rate limiting to noisy clients.
- Fail open only for explicitly approved non-sensitive paths.

## Escalation criteria
Escalate to identity platform owners when authentication failure rate exceeds 3 percent for a production region or impacts account login.
