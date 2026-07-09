# Authentication Failure

## Symptoms
- Elevated 401 and 403 responses from auth-service or api-gateway.
- Login and token refresh flows fail disproportionately.

## Investigation Steps
1. Validate signing keys, issuer configuration, and token refresh behavior.
2. Inspect recent auth changes and dependency latency.
3. Compare regions to isolate routing or identity-provider issues.

## Stabilization
- Roll back the auth-path change if a release triggered the spike.
- Coordinate with identity platform owners before broad customer impact grows.
