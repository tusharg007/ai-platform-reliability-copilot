# Demo

## Local Demo Flow

1. Run `scripts/run_demo.ps1`.
2. Start the API with `scripts/run_api.ps1`.
3. Start the dashboard with `scripts/run_dashboard.ps1`.
4. Review generated assets in `assets/` and reports in `reports/`.

## Suggested Demo Narrative

- Show the generated service risk table and highlight the riskiest service.
- Call out that the outputs were recalibrated to avoid saturated risk scoring and empty chart slices.
- Note that alert severity is calibrated to show varied levels instead of pushing every major anomaly to `critical`.
- Open `/docs` in FastAPI to demonstrate production-style API contracts.
- Ask the copilot why a database timeout or deployment regression occurred.
- Explain that the system uses synthetic platform logs and simulated incidents to stay honest and reproducible.

## Deployment Notes

- The local demo uses Streamlit plus FastAPI.
- The optional Render deployment path is FastAPI-only and is suitable for an API prototype demo.
- Render startup regenerates synthetic data and serves the validated API outputs without requiring external keys.
