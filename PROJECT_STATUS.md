# Project Status

## Current State

The repository has been upgraded into a production-oriented prototype for AI-assisted reliability analytics, anomaly detection, incident clustering, service risk scoring, and retrieval-backed incident intelligence using synthetic platform logs.

## What Works

- Synthetic log, deployment, and incident generation for seven services across multiple regions.
- Log ingestion with normalization, validation, hourly metric aggregation, and a data quality report.
- Isolation Forest and rolling z-score anomaly detection.
- Incident clustering and 0-100 service risk scoring.
- TF-IDF retrieval over runbooks and incident history plus template-based copilot responses.
- FastAPI endpoints and a Streamlit dashboard backed by generated CSV outputs.
- Screenshot generation, evaluation reports, smoke test, pytest suite, Docker assets, and CI workflow.

## What Is Missing

- No real production telemetry ingestion or live observability integrations.
- No real authentication or multi-user workflow.
- No online learning, advanced vector database, or LLM dependency by default.
- No cloud deployment verification in this repository state.

## What Changed

- Replaced the older backend/frontend-centered demo structure with a clearer pipeline under `src/`, `api/`, and `dashboard/`.
- Added raw, processed, prediction, sample, runbook, report, asset, script, and evaluation artifacts.
- Rewrote documentation to support recruiter-friendly, honest portfolio positioning.
- Recalibrated synthetic traffic, alerting, incident clustering, and service risk scoring to eliminate empty charts and saturated `100` risk outputs.

## How To Run

1. Install dependencies with `pip install -r requirements.txt`.
2. Run `python -m src.smoke_test` for the full local pipeline.
3. Start the API with `python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`.
4. Start the dashboard with `python -m streamlit run dashboard/app.py`.

## Verified Commands

The following commands were verified locally during this upgrade on 2026-07-10:

1. `python -m compileall src api tests`
2. `python -m src.validate_outputs`
3. `python -m src.smoke_test`
4. `pytest tests -q`

## Remaining Limitations

- Metrics are approximate because they are validated against synthetic ground truth.
- Dashboard screenshots are matplotlib-generated stand-ins unless browser capture is added later.
- The copilot is retrieval-and-template based unless an optional external LLM is introduced.
