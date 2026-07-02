"""Streamlit dashboard for the AI Platform Reliability Copilot."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def api_post(path: str, payload: dict) -> dict:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def api_get(path: str) -> dict:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=15)
    response.raise_for_status()
    return response.json()


@st.cache_data
def load_logs() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "synthetic_logs.csv", parse_dates=["timestamp"])


@st.cache_data
def load_metrics() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "service_metrics.csv", parse_dates=["timestamp"])


st.set_page_config(page_title="AI Platform Reliability Copilot", page_icon="A", layout="wide")
st.title("AI Platform Reliability Copilot")
st.caption("RAG, agent tools, log analytics, anomaly detection, and incident summaries for backend platform reliability.")

logs = load_logs()
metrics = load_metrics()
services = sorted(logs["service_name"].unique())
regions = sorted(logs["region"].unique())


def default_prompt(service_name: str, region_name: str | None) -> str:
    scoped_logs = logs[logs["service_name"] == service_name]
    scoped_metrics = metrics[metrics["service_name"] == service_name]
    if region_name:
        scoped_logs = scoped_logs[scoped_logs["region"] == region_name]
        scoped_metrics = scoped_metrics[scoped_metrics["region"] == region_name]

    scope = f"{service_name} in {region_name}" if region_name else f"{service_name} across all regions"
    version = ""
    if not scoped_metrics.empty:
        latest_version = scoped_metrics.sort_values("timestamp")["deployment_version"].iloc[-1]
        version = f" after deployment {latest_version}"
    if not scoped_logs.empty:
        errors = scoped_logs[(scoped_logs["status_code"] >= 500) & (scoped_logs["error_type"].fillna("") != "")]
        if not errors.empty:
            top_error = errors["error_type"].value_counts().idxmax()
            return f"Why is {scope} showing {top_error} errors{version}?"
    return f"Summarize reliability risks for {scope}{version}."


def render_bullets(items: list[str]) -> None:
    for item in items:
        st.markdown(f"- {item}")

with st.sidebar:
    st.header("Controls")
    service = st.selectbox("Service", services, index=services.index("payment-service") if "payment-service" in services else 0)
    region = st.selectbox("Region", ["all"] + regions, index=(["all"] + regions).index("ap-south") if "ap-south" in regions else 0)
    selected_region = None if region == "all" else region

prompt_context = f"{service}|{selected_region or 'all'}"
if st.session_state.get("prompt_context") != prompt_context:
    st.session_state["chat_query"] = default_prompt(service, selected_region)
    st.session_state["prompt_context"] = prompt_context

tab_chat, tab_health, tab_logs, tab_anomaly, tab_incident, tab_sources = st.tabs(
    ["AI Copilot Chat", "Service Health", "Log Explorer", "Anomaly Detection", "Incident Summary", "RAG Sources"]
)

with tab_chat:
    query = st.text_area(
        "Ask the copilot",
        key="chat_query",
        height=90,
    )
    if st.button("Analyze", type="primary"):
        try:
            result = api_post("/chat", {"query": query, "service_name": service, "region": selected_region})
            st.caption(f"Severity estimate: {result.get('severity', 'n/a')}")
            st.subheader("Answer")
            st.markdown(result["answer"])
            st.subheader("Evidence")
            render_bullets(result["evidence"])
            st.subheader("Recommended actions")
            render_bullets(result["recommended_actions"])
        except Exception as exc:
            st.error(f"Backend unavailable or request failed: {exc}")

with tab_health:
    try:
        summary = api_get("/metrics/summary")
        kpis = summary["kpis"]
    except Exception:
        error_rate = float((logs["status_code"] >= 500).mean())
        kpis = {
            "total_services": len(services),
            "average_latency": round(float(logs["latency_ms"].mean()), 2),
            "p95_latency": round(float(logs["latency_ms"].quantile(0.95)), 2),
            "overall_error_rate": round(error_rate, 4),
            "most_affected_region": logs[logs["status_code"] >= 500]["region"].mode().iloc[0],
        }
    cols = st.columns(5)
    cols[0].metric("Services", kpis["total_services"])
    cols[1].metric("Avg latency", f"{kpis['average_latency']} ms")
    cols[2].metric("P95 latency", f"{kpis['p95_latency']} ms")
    cols[3].metric("Error rate", f"{kpis['overall_error_rate'] * 100:.2f}%")
    cols[4].metric("Most affected region", kpis["most_affected_region"])

    service_error_rate = logs.assign(is_error=logs["status_code"] >= 500).groupby("service_name")["is_error"].mean().sort_values()
    st.bar_chart(service_error_rate)
    metric_slice = metrics[metrics["service_name"] == service].set_index("timestamp")
    st.line_chart(metric_slice[["p95_latency_ms", "error_rate"]])

with tab_logs:
    filtered = logs[logs["service_name"] == service]
    if selected_region:
        filtered = filtered[filtered["region"] == selected_region]
    st.dataframe(filtered.sort_values("timestamp", ascending=False).head(500), use_container_width=True)
    st.write("Top error types")
    st.bar_chart(filtered[filtered["error_type"].fillna("") != ""]["error_type"].value_counts())

with tab_anomaly:
    metric = st.selectbox("Metric", ["p95_latency_ms", "error_rate", "cpu_usage", "memory_usage", "request_count", "timeout_count"])
    if st.button("Detect anomalies"):
        try:
            result = api_post("/detect-anomalies", {"service_name": service, "region": selected_region, "metric_name": metric})
            st.metric("Health score", result["health_score"])
            st.dataframe(pd.DataFrame(result["anomalies"]), use_container_width=True)
        except Exception as exc:
            st.error(f"Backend unavailable or request failed: {exc}")

with tab_incident:
    if st.button("Generate incident summary"):
        try:
            result = api_post("/incident-summary", {"service_name": service, "region": selected_region})
            st.subheader("Summary")
            st.write(result["summary"])
            st.subheader("Root cause hypothesis")
            st.write(result["root_cause_hypothesis"])
            st.subheader("Action plan")
            render_bullets(result["action_plan"])
            st.subheader("Postmortem template")
            st.code(result["postmortem_template"], language="markdown")
        except Exception as exc:
            st.error(f"Backend unavailable or request failed: {exc}")

with tab_sources:
    for path in sorted((ROOT_DIR / "knowledge_base").glob("*.md")):
        with st.expander(path.name):
            st.markdown(path.read_text(encoding="utf-8"))
