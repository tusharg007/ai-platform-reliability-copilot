# Deployment Regression

## Symptoms
- Error rates and p95 latency increase shortly after a version change.
- The issue may be region-specific at first.

## Investigation Steps
1. Diff code, config, schema, and dependency changes in the new release.
2. Check whether only one region or service tier is impacted.
3. Compare logs before and after the deployment event.

## Stabilization
- Roll back or disable the change behind a feature flag.
- Freeze follow-up releases until the regression is understood.
