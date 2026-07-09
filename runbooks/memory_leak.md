# Memory Leak

## Symptoms
- Memory usage rises steadily over time.
- Restart frequency or OOM risk increases.
- Latency may degrade before hard failures appear.

## Investigation Steps
1. Compare memory growth by deployment version.
2. Inspect caches, retained objects, and long-lived workers.
3. Validate whether batch jobs or model inference paths hold references too long.

## Stabilization
- Restart the affected service if necessary.
- Roll back recent memory-affecting changes.
- Add heap profiling or stronger memory guardrails.
