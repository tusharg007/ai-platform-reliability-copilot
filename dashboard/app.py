"""Streamlit dashboard for recalibrated reliability analytics."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR


API_URL = st.secrets.get("API_BASE_URL", "http://localhost:8000")


@st.cache_data
def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for column in ["hour", "timestamp", "start_time", "end_time"]:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], utc=True, errors="ignore")
    return df


def api_json(method: str, path: str, payload: dict | None = None) -> dict | list:
    response = requests.request(method, f"{API_URL}{path}", json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="AI Platform Reliability Copilot", layout="wide")
st.title("AI Platform Reliability Copilot")
st.caption("Production-oriented prototype using synthetic platform logs and simulated incidents.")

page = st.sidebar.radio(
    "Page",
    [
        "Overview",
        "Service Health",
        "Anomaly Detection",
        "Incident Timeline",
        "Root Cause Analysis",
        "Copilot Assistant",
        "Model Evaluation",
    ],
)

metrics_df = load_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
alerts_df = load_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
incidents_df = load_csv(PREDICTIONS_DIR / "incidents.csv")
risk_df = load_csv(PREDICTIONS_DIR / "service_risk_scores.csv")
metrics_json = json.loads((REPORTS_DIR / "metrics.json").read_text(encoding="utf-8")) if (REPORTS_DIR / "metrics.json").exists() else {}

if page == "Overview":
    kpis = api_json("GET", "/kpis/overview")
    cols = st.columns(5)
    cols[0].metric("Services", kpis["services_monitored"])
    cols[1].metric("Avg Error Rate", f"{kpis['latest_average_error_rate'] * 100:.2f}%")
    cols[2].metric("Avg P95 Latency", f"{kpis['latest_average_p95_latency_ms']:.1f} ms")
    cols[3].metric("High Risk Services", kpis["high_risk_services"])
    cols[4].metric("Clustered Incidents", kpis["clustered_incidents"])

    latest_window = metrics_df[metrics_df["hour"] >= metrics_df["hour"].max() - pd.Timedelta(hours=24)]
    st.subheader("24h Average Error Rate by Service")
    st.bar_chart(latest_window.groupby("service_name")["error_rate"].mean().sort_values(ascending=False))
    st.subheader("Reliability Risk Scores")
    st.bar_chart(risk_df.set_index("service_name")["risk_score"])

if page == "Service Health":
    st.subheader("Service Health and Explainability")
    st.dataframe(risk_df, use_container_width=True)
    st.bar_chart(risk_df.set_index("service_name")["risk_score"])
    st.write("Risk band distribution")
    st.bar_chart(risk_df["risk_band"].value_counts())

if page == "Anomaly Detection":
    st.subheader("Alerts Over Time")
    trend = alerts_df.groupby([alerts_df["timestamp"].dt.floor("h"), "severity"]).size().unstack(fill_value=0)
    st.line_chart(trend)
    st.subheader("Alert Type Distribution")
    st.bar_chart(alerts_df["alert_type"].value_counts())
    st.subheader("Recent High/Critical Alerts")
    st.dataframe(
        alerts_df[alerts_df["severity"].isin(["high", "critical"])].sort_values("timestamp", ascending=False).head(25),
        use_container_width=True,
    )

if page == "Incident Timeline":
    st.subheader("Clustered Incidents")
    st.dataframe(incidents_df.sort_values("start_time", ascending=False), use_container_width=True)
    st.subheader("Incident Severity Distribution")
    st.bar_chart(incidents_df["severity"].value_counts())

if page == "Root Cause Analysis":
    st.markdown((REPORTS_DIR / "root_cause_analysis.md").read_text(encoding="utf-8"))

if page == "Copilot Assistant":
    question = st.text_input("Ask a reliability question", "Why is payment-service high risk in the latest window?")
    if st.button("Ask Copilot"):
        response = api_json("POST", "/copilot/ask", {"question": question})
        st.json(response["response"])

if page == "Model Evaluation":
    st.json(metrics_json)
    st.markdown((REPORTS_DIR / "model_evaluation.md").read_text(encoding="utf-8"))
    st.subheader("Risk Score Distribution")
    st.bar_chart(risk_df.set_index("service_name")["risk_score"])
