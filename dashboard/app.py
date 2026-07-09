"""Streamlit dashboard for the reliability intelligence prototype."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from src.config import PREDICTIONS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR


API_URL = st.secrets.get("API_BASE_URL", "http://localhost:8000")


@st.cache_data
def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def api_json(method: str, path: str, payload: dict | None = None) -> dict | list:
    response = requests.request(method, f"{API_URL}{path}", json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="AI Platform Reliability Copilot", layout="wide")
st.title("AI Platform Reliability Copilot")
st.caption("AI-assisted reliability analytics over synthetic platform logs and simulated incidents.")

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
metrics_json = (REPORTS_DIR / "metrics.json").read_text(encoding="utf-8") if (REPORTS_DIR / "metrics.json").exists() else "{}"

if page == "Overview":
    kpis = api_json("GET", "/kpis/overview")
    cols = st.columns(5)
    cols[0].metric("Services", kpis["services_monitored"])
    cols[1].metric("Avg Error Rate", f"{kpis['latest_average_error_rate'] * 100:.2f}%")
    cols[2].metric("Avg P95 Latency", f"{kpis['latest_average_p95_latency_ms']:.1f} ms")
    cols[3].metric("High Risk Services", kpis["high_risk_services"])
    cols[4].metric("Clustered Incidents", kpis["clustered_incidents"])
    st.subheader("Top Risk Services")
    st.dataframe(risk_df.head(10), use_container_width=True)

if page == "Service Health":
    st.subheader("Service Risk Scores")
    st.bar_chart(risk_df.set_index("service_name")["risk_score"])
    st.dataframe(risk_df, use_container_width=True)

if page == "Anomaly Detection":
    st.subheader("Recent Reliability Alerts")
    st.dataframe(alerts_df.sort_values("timestamp", ascending=False).head(50), use_container_width=True)
    trend = alerts_df.groupby(["service_name", "severity"]).size().reset_index(name="count")
    st.dataframe(trend, use_container_width=True)

if page == "Incident Timeline":
    st.subheader("Clustered Incidents")
    st.dataframe(incidents_df.sort_values("start_time", ascending=False), use_container_width=True)

if page == "Root Cause Analysis":
    st.subheader("Root Cause Notes")
    st.markdown((REPORTS_DIR / "root_cause_analysis.md").read_text(encoding="utf-8"))

if page == "Copilot Assistant":
    st.subheader("Copilot Assistant")
    question = st.text_input("Ask a reliability question", "Why did database-service trigger upstream timeouts?")
    if st.button("Ask Copilot"):
        response = api_json("POST", "/copilot/ask", {"question": question})
        st.json(response["response"])

if page == "Model Evaluation":
    st.subheader("Evaluation Metrics")
    st.code(metrics_json, language="json")
    st.markdown((REPORTS_DIR / "model_evaluation.md").read_text(encoding="utf-8"))
