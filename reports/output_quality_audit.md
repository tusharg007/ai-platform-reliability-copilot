# Output Quality Audit

## Summary

The original analytics outputs were not professionally acceptable because the pipeline was producing sparse, weakly differentiated service-hour metrics and then applying saturated downstream scoring. This caused empty-looking error-rate visuals, identical service health charts, and all services collapsing to a risk score of `100`.

## Root Causes In The Previous Version

### Why the error rate chart looked empty

- The synthetic generator produced only one row per service per five-minute interval.
- Hourly request counts therefore collapsed to a constant `12` rows per service-hour.
- The screenshot used the single latest hour per service, and that particular slice often had `0` 5xx events.
- The chart was technically not empty, but it visually collapsed to near-zero bars because the latest slice had no meaningful recent error variation.

### Why all service risk scores became `100`

- The prior scoring formula added large raw terms directly: anomaly count, incident count, latency, CPU, memory, DB latency, and queue lag.
- Incident clustering was also too permissive, so many alerts became many incidents per service.
- The formula hit the `min(100, ...)` cap almost immediately for every service, eliminating any ranking value.

### Whether anomaly detection previously produced meaningful variation

- It produced alerts, but variation was weakly structured.
- Most alerts were labeled `generic_anomaly`, which reduced interpretability.
- Severity calibration was compressed toward medium/high without enough alert-type specificity.

### Whether incident clustering previously looked realistic

- No. Alerts were clustered mostly by service and time gap, which over-generated incidents.
- Deployment context, root-cause type, and cross-service correlation were underused.
- This inflated incident counts and contaminated downstream risk scoring.

### Whether service-level metrics had enough variance

- No. Request counts barely varied because the generator emitted a fixed number of rows per hour.
- That limited the realism of traffic shifts, error bursts, and p95 behavior.
- Services also lacked distinct enough request-volume and status-code patterns.

### Whether the old screenshots honestly represented outputs

- Yes, but the outputs themselves were poorly calibrated.
- The screenshots exposed real weaknesses in the data generation and scoring pipeline rather than hiding them.

## Recalibration Changes

- Replaced fixed-row log generation with variable request volumes per service and per hour.
- Added distinct service baselines for volume, latency, error rate, CPU, memory, DB latency, queue lag, and status-code mix.
- Reworked incidents so they align with service-specific and region-specific behavior.
- Upgraded ingestion to build richer hourly metrics with 4xx/5xx rates and incident flags.
- Replaced generic alert logic with typed alerts such as `latency_spike`, `queue_backlog`, `deployment_regression`, and `auth_failure_spike`.
- Replaced saturated additive risk scoring with percentile-based calibrated scoring and explainability fields.
- Added validation so empty or saturated charts fail the pipeline.

## Current Output Quality Assessment

### Error-rate view

- The overview now uses the recent 24-hour average error rate by service instead of a single sparse hour.
- Services now show differentiated non-zero recent error rates.

### Risk score quality

- Scores are now spread across four bands: `Low`, `Medium`, `High`, and `Critical`.
- Current score span is approximately `49.47` points.
- Services no longer collapse to identical values.

### Anomaly detection quality

- Alerts are non-empty and include multiple alert types.
- Severity now spans `low`, `medium`, `high`, and `critical`.
- Alert types reflect plausible platform scenarios rather than generic catch-alls.

### Incident clustering quality

- Incidents are fewer than alerts and now carry alert counts, severity, symptoms, and root-cause labels.
- Known incident windows are reflected in the clustered outputs.

### Screenshot honesty

- Screenshots are generated directly from the recalibrated CSV outputs.
- Validation fails if the underlying chart inputs are empty or saturated.

## Remaining Limitations

- Evaluation metrics remain approximate because they use synthetic ground truth.
- Incident counts are still higher than a real production system because the prototype preserves alert visibility for portfolio demonstration.
- The system remains a production-oriented prototype using synthetic platform logs, not real telemetry.
