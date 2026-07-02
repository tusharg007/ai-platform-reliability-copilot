# Deployment Guide

## Overview
Production services use canary deployments, health checks, and rollback automation to reduce platform risk.

## Common symptoms
- Error rate rises immediately after a new version.
- P95 latency regression in only one region.
- Logs show new exception signatures tied to deployment version.
- Canary health checks fail while baseline remains stable.

## Key metrics to check
- Error rate by deployment version.
- Latency by version and region.
- Rollout percentage and pod restart count.
- Database migration duration.

## Common root causes
- Bad configuration in the new deployment.
- Backward-incompatible schema or API change.
- Resource limits too low for new runtime behavior.
- Missing environment variable or secret.

## Debugging steps
1. Compare the failing version to the last stable version.
2. Check canary metrics before full rollout.
3. Inspect logs for missing configuration, timeout, or schema errors.
4. Roll back if customer-facing error rate crosses the service threshold.

## Recommended fixes
- Roll back to the last stable version.
- Pause rollout and isolate canary traffic.
- Add preflight checks for required configuration.
- Run database migrations separately from app rollout.

## Escalation criteria
Escalate to release engineering when deployment-related failures affect multiple services or require coordinated rollback.
