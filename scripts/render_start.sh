#!/usr/bin/env bash
set -e

echo "Generating synthetic reliability data..."
python -m src.generate_synthetic_logs
python -m src.ingest_logs
python -m src.detect_anomalies
python -m src.incident_clustering
python -m src.service_risk_scoring
python -m src.evaluate_system
python -m src.validate_outputs
python -m src.smoke_test

echo "Starting FastAPI server..."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
