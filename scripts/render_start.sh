#!/usr/bin/env bash
set -e

export PYTHONPATH="${PYTHONPATH:-.}"

REQUIRED_FILES=(
  "data/predictions/service_risk_scores.csv"
  "data/predictions/incidents.csv"
  "data/predictions/reliability_alerts.csv"
  "data/processed/service_hourly_metrics.csv"
)

missing=false
for file in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$file" ]; then
    missing=true
    break
  fi
done

if [ "$missing" = false ]; then
  echo "Found existing generated CSV outputs. Skipping regeneration."
  python -m src.render_smoke_test
else
  echo "Required CSV outputs missing. Bootstrapping analytics pipeline..."
  python -m src.generate_synthetic_logs --quick
  python -m src.ingest_logs
  python -m src.detect_anomalies
  python -m src.incident_clustering
  python -m src.service_risk_scoring
  python -m src.evaluate_system
  python -m src.validate_outputs
  python -m src.render_smoke_test
fi

echo "Starting FastAPI server..."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
