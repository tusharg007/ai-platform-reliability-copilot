# Incident Response SOP

## Overview
Incident response turns ambiguous operational signals into a shared diagnosis, owner, action plan, and customer-impact summary.

## Common symptoms
- Multiple alerts across logs and metrics.
- Affected region or deployment version is unclear.
- Engineers repeatedly ask for the same context.
- Manual summaries lag behind the investigation.

## Key metrics to check
- Error rate, latency, timeout count, and request volume.
- Impacted services and regions.
- Deployment version and start time.
- Mitigation status and recovery trend.

## Common root causes
- Recent deployment regression.
- Downstream dependency degradation.
- Database saturation or lock contention.
- Traffic spike or retry storm.

## Debugging steps
1. Define the user impact, affected service, and affected region.
2. Establish incident start time from metrics.
3. Link logs, traces, deployments, and runbooks.
4. Assign owner and next action.
5. Update stakeholders every 15 minutes for SEV-1 or SEV-2.

## Recommended fixes
- Mitigate first, then diagnose deeply.
- Prefer rollback when a deployment is strongly correlated with impact.
- Record evidence and decisions in the incident timeline.
- Create follow-up work for prevention and observability gaps.

## Escalation criteria
Escalate to SEV-2 for sustained production impact, revenue impact, or cross-service degradation.
