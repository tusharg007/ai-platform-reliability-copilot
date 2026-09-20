"""Production Streamlit dashboard for the AI Platform Reliability Copilot v2.0.

New in v2.0:
  - Real-time KPI cards from /dashboard/kpis endpoint
  - Incident Clustering tab with blast radius visualisation
  - Risk Scoring tab with multi-dimensional breakdown
  - Root-Cause Analysis tab with causal chain display
  - Fleet Risk heatmap (service × health score)
  - Streaming ingestion status panel
  - Feedback integration on every AI response
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"

try:
    API_BASE_URL = st.secrets.get("API_BASE_URL", os.getenv("API_BASE_URL", "http://localhost:8000"))
except Exception:
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


# ─────────────────────────────────────────────────────────────────────────────
#  API Helpers
# ─────────────────────────────────────────────────────────────────────────────

def api_post(path: str, payload: dict) -> dict:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def api_get(path: str) -> dict:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def load_logs() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "synthetic_logs.csv", parse_dates=["timestamp"])


@st.cache_data(ttl=60)
def load_metrics() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "service_metrics.csv", parse_dates=["timestamp"])


# ─────────────────────────────────────────────────────────────────────────────
#  Page Configuration
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Platform Reliability Copilot",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🛡️ AI Platform Reliability Copilot v2.0")
st.caption(
    "Production-grade platform reliability: real-time anomaly detection, incident clustering, "
    "risk scoring, runbook retrieval, and LLM-powered root-cause recommendations."
)

logs = load_logs()
metrics = load_metrics()
services = sorted(logs["service_name"].unique())
regions = sorted(logs["region"].unique())


# ─────────────────────────────────────────────────────────────────────────────
#  Sidebar Controls
# ─────────────────────────────────────────────────────────────────────────────

def render_bullets(items: list[str]) -> None:
    for item in items:
        st.markdown(f"- {item}")


with st.sidebar:
    st.header("🎛️ Controls")
    service = st.selectbox(
        "Service",
        services,
        index=services.index("payment-service") if "payment-service" in services else 0,
    )
    region = st.selectbox(
        "Region",
        ["all"] + regions,
        index=(["all"] + regions).index("ap-south") if "ap-south" in regions else 0,
    )
    selected_region = None if region == "all" else region

    st.divider()
    st.subheader("📡 Pipeline Status")
    try:
        pipeline = api_get("/pipeline/status")
        st.success("✅ Backend Connected")
        ingest = pipeline.get("ingestion", {})
        st.metric("Events Ingested", ingest.get("total_events_ingested", 0))
        st.metric("Active Alerts", ingest.get("active_alerts", 0))
        st.caption(f"DB: `{pipeline.get('database_url', 'N/A')}`")
    except Exception:
        st.warning("⚠️ Backend Offline — using local CSV data")

    st.divider()
    st.caption("v2.0 | Powered by FastAPI + Streamlit")


# ─────────────────────────────────────────────────────────────────────────────
#  Smart Default Prompt
# ─────────────────────────────────────────────────────────────────────────────

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
        errors = scoped_logs[
            (scoped_logs["status_code"] >= 500) & (scoped_logs["error_type"].fillna("") != "")
        ]
        if not errors.empty:
            top_error = errors["error_type"].value_counts().idxmax()
            return f"Why is {scope} showing {top_error} errors{version}?"
    return f"Summarize reliability risks for {scope}{version}."


prompt_context = f"{service}|{selected_region or 'all'}"
if st.session_state.get("prompt_context") != prompt_context:
    st.session_state["chat_query"] = default_prompt(service, selected_region)
    st.session_state["prompt_context"] = prompt_context


# ─────────────────────────────────────────────────────────────────────────────
#  Tabs
# ─────────────────────────────────────────────────────────────────────────────

(
    tab_chat,
    tab_health,
    tab_rca,
    tab_risk,
    tab_cluster,
    tab_logs,
    tab_anomaly,
    tab_incident,
    tab_sources,
) = st.tabs([
    "🤖 AI Copilot",
    "📊 Fleet Health",
    "🔍 Root-Cause",
    "⚖️ Risk Score",
    "🔗 Incident Clusters",
    "📋 Log Explorer",
    "🚨 Anomaly Detection",
    "📄 Incident Summary",
    "📚 Runbooks",
])


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: AI Copilot Chat
# ─────────────────────────────────────────────────────────────────────────────

with tab_chat:
    query = st.text_area("Ask the copilot", key="chat_query", height=90)
    col_btn, col_session = st.columns([2, 3])
    with col_btn:
        analyze_clicked = st.button("🔍 Analyze", type="primary")
    with col_session:
        session_id = st.text_input("Session ID (optional)", placeholder="my-session-001")

    if analyze_clicked:
        try:
            with st.spinner("Running multi-step analysis..."):
                result = api_post("/chat", {
                    "query": query,
                    "service_name": service,
                    "region": selected_region,
                    "session_id": session_id or None,
                })

            # KPI row
            kpi_cols = st.columns(5)
            kpi_cols[0].metric("Severity", result.get("severity", "N/A"))
            kpi_cols[1].metric("Risk Score", f"{result.get('risk_score', 0):.3f}")
            kpi_cols[2].metric("Confidence", f"{result.get('confidence', 0):.0%}")
            kpi_cols[3].metric("Est. MTTR", f"{result.get('estimated_mttr_minutes', '?')} min")
            kpi_cols[4].metric("Latency", f"{result.get('latency_ms', 0):.0f} ms")

            st.subheader("💬 Answer")
            st.markdown(result["answer"])

            # Causal chain
            causal_chain = result.get("causal_chain", [])
            if causal_chain:
                st.subheader("🔗 Causal Chain")
                for step in causal_chain:
                    with st.expander(f"Step {step['sequence']}: {step['event'][:80]}"):
                        st.caption(f"Evidence: {step['evidence']}")

            col_ev, col_act = st.columns(2)
            with col_ev:
                st.subheader("🔬 Evidence")
                render_bullets(result["evidence"])
            with col_act:
                st.subheader("✅ Recommended Actions")
                render_bullets(result["recommended_actions"])

            if result.get("sources"):
                with st.expander("📚 Runbook Sources"):
                    for src in result["sources"]:
                        st.markdown(f"**{src['source']}** (section: {src.get('section', 'N/A')}, score: {src.get('score', 0):.3f})")
                        st.text(src["text"][:300] + "...")

            # Feedback
            st.divider()
            st.subheader("📝 Rate this response")
            rating = st.slider("Quality rating", 1, 5, 4)
            comment = st.text_input("Comments (optional)")
            if st.button("Submit Feedback"):
                api_post("/feedback", {
                    "query": query,
                    "answer": result["answer"][:500],
                    "rating": rating,
                    "comments": comment,
                    "session_id": session_id or None,
                    "service_name": service,
                })
                st.success("Feedback recorded ✓")

        except Exception as exc:
            st.error(f"Backend unavailable: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Fleet Health
# ─────────────────────────────────────────────────────────────────────────────

with tab_health:
    try:
        kpis_data = api_get("/dashboard/kpis")
    except Exception:
        error_rate = float((logs["status_code"] >= 500).mean())
        kpis_data = {
            "total_services": len(services),
            "healthy_services": len(services),
            "degraded_services": 0,
            "critical_services": 0,
            "average_latency_ms": round(float(logs["latency_ms"].mean()), 2),
            "p95_latency_ms": round(float(logs["latency_ms"].quantile(0.95)), 2),
            "overall_error_rate": round(error_rate, 4),
            "most_affected_region": logs[logs["status_code"] >= 500]["region"].mode().iloc[0],
            "active_incident_count": 0,
            "fleet_risk_score": 0.0,
            "fleet_severity": "N/A",
        }

    # KPI banner
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("🟢 Healthy", kpis_data["healthy_services"])
    c2.metric("🟡 Degraded", kpis_data["degraded_services"])
    c3.metric("🔴 Critical", kpis_data["critical_services"])
    c4.metric("P95 Latency", f"{kpis_data['p95_latency_ms']} ms")
    c5.metric("Error Rate", f"{kpis_data['overall_error_rate']*100:.2f}%")
    c6.metric("Fleet Risk", f"{kpis_data['fleet_risk_score']:.3f}")

    st.divider()

    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Error Rate by Service")
        svc_err = (
            logs.assign(is_error=logs["status_code"] >= 500)
            .groupby("service_name")["is_error"]
            .mean()
            .sort_values()
        )
        st.bar_chart(svc_err)

    with col_r:
        st.subheader(f"Time-Series Metrics — {service}")
        metric_slice = metrics[metrics["service_name"] == service].set_index("timestamp")
        if selected_region:
            metric_slice = metrics[
                (metrics["service_name"] == service) & (metrics["region"] == selected_region)
            ].set_index("timestamp")
        if not metric_slice.empty:
            st.line_chart(metric_slice[["p95_latency_ms", "error_rate"]])
        else:
            st.info("No metrics for selected service/region.")

    # Fleet risk heatmap via fleet-risk API
    try:
        fleet = api_get("/fleet-risk")
        st.subheader("Fleet Risk Heatmap")
        per_svc = fleet.get("per_service_risk", [])
        if per_svc:
            df_risk = pd.DataFrame(per_svc)[["service_name", "composite_score", "severity"]]
            df_risk = df_risk.sort_values("composite_score", ascending=False)
            df_risk.columns = ["Service", "Risk Score", "Severity"]
            st.dataframe(
                df_risk.style.background_gradient(subset=["Risk Score"], cmap="RdYlGn_r"),
                use_container_width=True,
            )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Root-Cause Analysis
# ─────────────────────────────────────────────────────────────────────────────

with tab_rca:
    st.subheader("🔍 Root-Cause Analysis")
    st.caption("Synthesises telemetry, anomalies, runbooks, and risk data into a structured causal chain.")

    if st.button("🔍 Analyze Root Cause", type="primary"):
        try:
            with st.spinner("Running RCA pipeline..."):
                rca = api_post("/root-cause", {"service_name": service, "region": selected_region})

            # Header metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Severity", rca.get("severity", "N/A"))
            m2.metric("Risk Score", f"{rca.get('risk_score', 0):.3f}")
            m3.metric("Confidence", f"{rca.get('confidence', 0):.0%}")
            m4.metric("Est. MTTR", f"{rca.get('estimated_mttr_minutes', '?')} min")

            st.divider()
            st.subheader("🔗 Causal Chain")
            for step in rca.get("causal_chain", []):
                st.markdown(f"**Step {step['sequence']}:** {step['event']}")
                st.caption(f"  Evidence: {step['evidence']}")

            st.subheader("💡 Root Cause")
            st.info(rca.get("root_cause", ""))

            col_ev, col_act = st.columns(2)
            with col_ev:
                st.subheader("🔬 Evidence")
                render_bullets(rca.get("evidence", []))
            with col_act:
                st.subheader("✅ Recommended Actions")
                render_bullets(rca.get("recommended_actions", []))

            if rca.get("runbook_references"):
                st.subheader("📚 Runbook References")
                for ref in rca["runbook_references"]:
                    st.markdown(f"- `{ref}`")

            st.caption(f"Generated via: {rca.get('generation_method', 'deterministic')} | {rca.get('generated_at', '')}")
        except Exception as exc:
            st.error(f"RCA failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Risk Score
# ─────────────────────────────────────────────────────────────────────────────

with tab_risk:
    st.subheader("⚖️ Multi-Dimensional Risk Score")
    error_type_input = st.text_input("Error type (optional)", placeholder="DB_CONNECTION_TIMEOUT")

    if st.button("Calculate Risk Score", type="primary"):
        try:
            risk = api_post("/risk-score", {
                "service_name": service,
                "region": selected_region,
                "error_type": error_type_input or None,
            })

            # Big risk number
            st.metric(
                label=f"Composite Risk Score — {risk['severity']}",
                value=f"{risk['composite_score']:.3f}",
                delta=f"SLO burn: {risk['slo_burn_score']:.2f}",
            )

            # Dimension bars
            dim_cols = st.columns(5)
            dim_cols[0].metric("Blast Radius", f"{risk['blast_radius_score']:.2f}")
            dim_cols[1].metric("Velocity", f"{risk['velocity_score']:.2f}")
            dim_cols[2].metric("SLO Burn", f"{risk['slo_burn_score']:.2f}")
            dim_cols[3].metric("Historical", f"{risk['historical_score']:.2f}")
            dim_cols[4].metric("Revenue", f"{risk['revenue_score']:.2f}")

            st.subheader("Contributing Factors")
            for factor in risk.get("contributing_factors", []):
                st.markdown(f"- {factor}")
        except Exception as exc:
            st.error(f"Risk scoring failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Incident Clusters
# ─────────────────────────────────────────────────────────────────────────────

with tab_cluster:
    st.subheader("🔗 Incident Clustering")
    st.caption("Groups related incident signals by semantic similarity to identify correlated failures.")
    window = st.slider("Analysis window (hours)", 1, 24, 4)

    if st.button("🔗 Run Clustering", type="primary"):
        try:
            with st.spinner("Running HDBSCAN clustering..."):
                result = api_post("/cluster-incidents", {"window_hours": window})

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Signals", result["total_signals"])
            c2.metric("Clusters Found", len(result["clusters"]))
            c3.metric("Unclustered", len(result["unclustered"]))

            br = result.get("blast_radius_summary", {})
            if br:
                st.info(
                    f"**Blast Radius:** {br.get('services_count', 0)} services × "
                    f"{br.get('regions_count', 0)} regions affected"
                )

            if result["clusters"]:
                st.subheader("Active Clusters")
                for cluster in result["clusters"]:
                    with st.expander(
                        f"🔴 {cluster['cluster_id']} — {cluster['centroid_service']} "
                        f"({cluster['centroid_error_type']}) — {cluster['member_count']} signals"
                    ):
                        c_a, c_b = st.columns(2)
                        c_a.metric("Blast Radius", f"{cluster['blast_radius']:.2f}")
                        c_b.metric("Velocity", f"{cluster['velocity']:.2f}")
                        st.write(f"**Affected services:** {', '.join(cluster['affected_services'])}")
                        st.write(f"**Affected regions:** {', '.join(cluster['affected_regions'])}")
                        st.write(f"**Error types:** {', '.join(cluster['error_types'])}")

                        hist = cluster.get("historical_matches", [])
                        if hist:
                            st.subheader("Historical Similar Incidents")
                            for match in hist:
                                st.markdown(
                                    f"- **{match['incident_id']}** (similarity: {match['similarity_score']:.2f}) — "
                                    f"MTTR: {match['duration_minutes']} min | "
                                    f"Resolution: {match['resolution'][:100]}"
                                )
            else:
                st.success("✅ No incident clusters detected in the selected window.")

            if result["unclustered"]:
                with st.expander(f"Unclustered signals ({len(result['unclustered'])})"):
                    st.dataframe(pd.DataFrame(result["unclustered"]), use_container_width=True)
        except Exception as exc:
            st.error(f"Clustering failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Log Explorer
# ─────────────────────────────────────────────────────────────────────────────

with tab_logs:
    filtered = logs[logs["service_name"] == service]
    if selected_region:
        filtered = filtered[filtered["region"] == selected_region]
    st.dataframe(
        filtered.sort_values("timestamp", ascending=False).head(500),
        use_container_width=True,
    )
    col_err, col_svc = st.columns(2)
    with col_err:
        st.write("Top Error Types")
        errors_only = filtered[filtered["error_type"].fillna("") != ""]["error_type"]
        if not errors_only.empty:
            st.bar_chart(errors_only.value_counts())
    with col_svc:
        st.write("Status Code Distribution")
        st.bar_chart(filtered["status_code"].value_counts())


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Anomaly Detection
# ─────────────────────────────────────────────────────────────────────────────

with tab_anomaly:
    metric = st.selectbox(
        "Metric",
        ["p95_latency_ms", "error_rate", "cpu_usage", "memory_usage", "request_count", "timeout_count"],
    )
    if st.button("🚨 Detect Anomalies", type="primary"):
        try:
            result = api_post("/detect-anomalies", {
                "service_name": service,
                "region": selected_region,
                "metric_name": metric,
            })
            a1, a2, a3 = st.columns(3)
            a1.metric("Health Score", result["health_score"])
            a2.metric("🔴 High Severity", result.get("high_count", 0))
            a3.metric("🟡 Medium Severity", result.get("medium_count", 0))
            if result["anomalies"]:
                st.dataframe(pd.DataFrame(result["anomalies"]), use_container_width=True)
            else:
                st.success("✅ No anomalies detected for selected metric.")
        except Exception as exc:
            st.error(f"Anomaly detection failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: Incident Summary
# ─────────────────────────────────────────────────────────────────────────────

with tab_incident:
    if st.button("📄 Generate Incident Summary", type="primary"):
        try:
            result = api_post("/incident-summary", {
                "service_name": service,
                "region": selected_region,
            })
            st.subheader("Summary")
            st.write(result["summary"])
            st.subheader("Root Cause Hypothesis")
            st.write(result["root_cause_hypothesis"])
            col_plan, col_post = st.columns(2)
            with col_plan:
                st.subheader("Action Plan")
                render_bullets(result["action_plan"])
            with col_post:
                st.subheader("Postmortem Template")
                st.code(result["postmortem_template"], language="markdown")
        except Exception as exc:
            st.error(f"Incident summary failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tab: RAG Sources / Runbooks
# ─────────────────────────────────────────────────────────────────────────────

with tab_sources:
    st.subheader("📚 Knowledge Base Runbooks")
    st.caption("Operational runbooks used by the RAG retrieval engine.")
    for path in sorted((ROOT_DIR / "knowledge_base").glob("*.md")):
        with st.expander(f"📄 {path.name}"):
            st.markdown(path.read_text(encoding="utf-8"))
