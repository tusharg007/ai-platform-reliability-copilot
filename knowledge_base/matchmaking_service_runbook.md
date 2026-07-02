# Matchmaking Service Runbook

## Overview
The matchmaking-service builds game sessions by pairing players according to latency, skill, region, and playlist constraints.

## Common symptoms
- Queue wait time increasing sharply.
- MATCHMAKING_QUEUE_TIMEOUT errors.
- Game session creation latency above target SLO.
- Uneven regional match allocation.

## Key metrics to check
- Queue depth and consumer lag.
- Match creation latency.
- Player request volume by playlist.
- Game-session-service success rate.

## Common root causes
- Insufficient queue consumers during traffic spikes.
- Playlist configuration reducing available player pools.
- Downstream game-session-service degradation.
- Regional capacity imbalance.

## Debugging steps
1. Compare queue depth against consumer throughput.
2. Segment failures by playlist and region.
3. Check downstream game-session-service errors.
4. Review recent playlist or matchmaking configuration changes.

## Recommended fixes
- Scale queue consumers.
- Relax overly strict matching constraints during incidents.
- Shift traffic away from constrained regions.
- Coordinate with game-session-service owners for downstream failures.

## Escalation criteria
Escalate when queue wait time breaches SLO for a major playlist for more than 15 minutes.
