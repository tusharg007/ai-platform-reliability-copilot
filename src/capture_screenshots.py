"""Generate validated screenshot assets from recalibrated analytics outputs."""

from __future__ import annotations

from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.config import ASSETS_DIR, PREDICTIONS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR, ensure_project_dirs
from src.copilot import answer_question


def capture_screenshots() -> list[Path]:
    ensure_project_dirs()
    metrics_df = pd.read_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
    alerts_df = pd.read_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
    incidents_df = pd.read_csv(PREDICTIONS_DIR / "incidents.csv")
    risk_df = pd.read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")
    metrics_json = json.loads((REPORTS_DIR / "metrics.json").read_text(encoding="utf-8"))

    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)
    incidents_df["end_time"] = pd.to_datetime(incidents_df["end_time"], utc=True)

    validate_for_visuals(metrics_df, alerts_df, incidents_df, risk_df)
    return [
        save_overview(metrics_df, alerts_df, incidents_df, risk_df),
        save_service_health(risk_df),
        save_anomaly_detection(alerts_df),
        save_incident_timeline(incidents_df),
        save_copilot_assistant(),
        save_model_evaluation(metrics_json, risk_df),
    ]


def validate_for_visuals(metrics_df: pd.DataFrame, alerts_df: pd.DataFrame, incidents_df: pd.DataFrame, risk_df: pd.DataFrame) -> None:
    latest_window = metrics_df[metrics_df["hour"] >= metrics_df["hour"].max() - pd.Timedelta(hours=24)]
    error_view = latest_window.groupby("service_name")["error_rate"].mean()
    if error_view.empty or error_view.sum() <= 0:
        raise ValueError("Latest error rate view is empty or all zero")
    if risk_df["risk_score"].nunique() <= 1:
        raise ValueError("Risk score chart would have identical bars")
    if alerts_df.empty or incidents_df.empty:
        raise ValueError("Alerts or incidents are empty; screenshots would be misleading")


def save_overview(metrics_df: pd.DataFrame, alerts_df: pd.DataFrame, incidents_df: pd.DataFrame, risk_df: pd.DataFrame) -> Path:
    latest_window = metrics_df[metrics_df["hour"] >= metrics_df["hour"].max() - pd.Timedelta(hours=24)]
    error_view = latest_window.groupby("service_name")["error_rate"].mean().sort_values(ascending=False) * 100
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    axes = axes.flatten()
    fig.suptitle("Reliability Overview", fontsize=16, fontweight="bold")

    axes[0].bar(error_view.index, error_view.values, color="#b54747")
    axes[0].set_title("24h Average Error Rate by Service")
    axes[0].set_ylabel("Error Rate (%)")
    axes[0].tick_params(axis="x", rotation=40)

    axes[1].bar(risk_df["service_name"], risk_df["risk_score"], color="#1f6f8b")
    axes[1].set_title("Reliability Risk Score by Service")
    axes[1].set_ylabel("Risk Score")
    axes[1].set_ylim(0, max(95, risk_df["risk_score"].max() + 5))
    axes[1].tick_params(axis="x", rotation=40)

    alert_counts = alerts_df["severity"].value_counts().reindex(["low", "medium", "high", "critical"], fill_value=0)
    axes[2].bar(alert_counts.index, alert_counts.values, color=["#6ea8fe", "#f9c74f", "#f9844a", "#d62828"])
    axes[2].set_title("Alert Count by Severity")
    axes[2].set_ylabel("Alerts")

    axes[3].axis("off")
    summary_text = (
        f"Services monitored: {risk_df['service_name'].nunique()}\n"
        f"Clustered incidents: {len(incidents_df)}\n"
        f"High-risk services: {int(risk_df['risk_band'].isin(['High', 'Critical']).sum())}\n"
        f"24h avg error rate: {latest_window['error_rate'].mean() * 100:.2f}%\n"
        f"Recent alerts: {len(alerts_df)}"
    )
    axes[3].text(0.02, 0.98, summary_text, va="top", fontsize=13)
    return save_figure(fig, "dashboard_overview.png")


def save_service_health(risk_df: pd.DataFrame) -> Path:
    fig = plt.figure(figsize=(14, 9))
    grid = fig.add_gridspec(2, 2)
    ax1 = fig.add_subplot(grid[:, 0])
    ax2 = fig.add_subplot(grid[0, 1])
    ax3 = fig.add_subplot(grid[1, 1])

    colors = risk_df["risk_band"].map({"Low": "#4caf50", "Medium": "#ffb300", "High": "#ef6c00", "Critical": "#c62828"})
    ax1.barh(risk_df["service_name"], risk_df["risk_score"], color=colors)
    ax1.set_title("Service Risk Scores")
    ax1.set_xlabel("Risk Score")
    ax1.invert_yaxis()

    band_counts = risk_df["risk_band"].value_counts().reindex(["Low", "Medium", "High", "Critical"], fill_value=0)
    ax2.bar(band_counts.index, band_counts.values, color=["#4caf50", "#ffb300", "#ef6c00", "#c62828"])
    ax2.set_title("Risk Band Distribution")

    ax3.axis("off")
    driver_table = risk_df[["service_name", "top_risk_driver_1", "top_risk_driver_2"]].copy()
    table = ax3.table(
        cellText=driver_table.values,
        colLabels=["Service", "Driver 1", "Driver 2"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)
    ax3.set_title("Top Risk Drivers")
    return save_figure(fig, "service_health.png")


def save_anomaly_detection(alerts_df: pd.DataFrame) -> Path:
    fig = plt.figure(figsize=(14, 9))
    grid = fig.add_gridspec(2, 2)
    ax1 = fig.add_subplot(grid[0, :])
    ax2 = fig.add_subplot(grid[1, 0])
    ax3 = fig.add_subplot(grid[1, 1])

    trend = alerts_df.groupby([alerts_df["timestamp"].dt.floor("h"), "severity"]).size().unstack(fill_value=0)
    trend.plot(ax=ax1)
    ax1.set_title("Alerts Over Time by Severity")
    ax1.set_ylabel("Alert Count")

    type_counts = alerts_df["alert_type"].value_counts().head(8)
    ax2.barh(type_counts.index, type_counts.values, color="#577590")
    ax2.set_title("Anomaly Type Distribution")

    ax3.axis("off")
    recent_high = alerts_df[alerts_df["severity"].isin(["high", "critical"])].sort_values("timestamp", ascending=False).head(8)
    table = ax3.table(
        cellText=recent_high[["service_name", "alert_type", "severity"]].values,
        colLabels=["Service", "Type", "Severity"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
    ax3.set_title("Recent High/Critical Alerts")
    return save_figure(fig, "anomaly_detection.png")


def save_incident_timeline(incidents_df: pd.DataFrame) -> Path:
    fig = plt.figure(figsize=(14, 9))
    grid = fig.add_gridspec(2, 2)
    ax1 = fig.add_subplot(grid[:, 0])
    ax2 = fig.add_subplot(grid[0, 1])
    ax3 = fig.add_subplot(grid[1, 1])

    incidents_by_day = incidents_df.groupby([incidents_df["start_time"].dt.date, "severity"]).size().unstack(fill_value=0)
    incidents_by_day = incidents_by_day.reindex(columns=["low", "medium", "high", "critical"], fill_value=0)
    incidents_by_day.plot(kind="bar", stacked=True, ax=ax1, color=["#6ea8fe", "#f9c74f", "#f9844a", "#d62828"])
    ax1.set_title("Incidents by Day and Severity")
    ax1.set_xlabel("Incident Start Date")
    ax1.set_ylabel("Incident Count")
    ax1.tick_params(axis="x", rotation=35)

    severity_counts = incidents_df["severity"].value_counts().reindex(["low", "medium", "high", "critical"], fill_value=0)
    ax2.bar(severity_counts.index, severity_counts.values, color=["#6ea8fe", "#f9c74f", "#f9844a", "#d62828"])
    ax2.set_title("Incident Severity Distribution")

    ax3.axis("off")
    top_incidents = incidents_df.assign(severity_rank=incidents_df["severity"].map({"critical": 4, "high": 3, "medium": 2, "low": 1}))
    top_incidents = top_incidents.sort_values(["severity_rank", "alert_count", "start_time"], ascending=[False, False, False]).head(8)
    table = ax3.table(
        cellText=top_incidents[["incident_id", "primary_service", "severity", "alert_count"]].values,
        colLabels=["Incident", "Primary Service", "Severity", "Alerts"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
    ax3.set_title("Top Recent / Highest Severity Incidents")
    return save_figure(fig, "incident_timeline.png")


def save_copilot_assistant() -> Path:
    response = answer_question("Why is payment-service risky in the latest synthetic incident window?")
    fig, ax = plt.subplots(figsize=(14, 8))
    ax.axis("off")
    lines = [
        "Copilot Assistant",
        "",
        "Question: Why is payment-service risky in the latest synthetic incident window?",
        "",
    ]
    for key in ["Summary", "Likely cause", "Supporting evidence", "Recommended next debugging steps", "Human review note"]:
        lines.append(f"{key}:")
        value = response[key]
        if isinstance(value, list):
            lines.extend([f"- {item}" for item in value[:6]])
        else:
            lines.append(str(value))
        lines.append("")
    ax.text(0.01, 0.99, "\n".join(lines), va="top", fontsize=11)
    return save_figure(fig, "copilot_assistant.png")


def save_model_evaluation(metrics_json: dict[str, object], risk_df: pd.DataFrame) -> Path:
    fig = plt.figure(figsize=(14, 8))
    grid = fig.add_gridspec(1, 2)
    ax1 = fig.add_subplot(grid[0, 0])
    ax2 = fig.add_subplot(grid[0, 1])

    metric_names = ["incident_detection_recall", "alert_precision_estimate", "incident_clustering_overlap", "retrieval_relevance_at_3"]
    pretty_labels = [
        "Incident Detection Recall",
        "Alert Precision Estimate",
        "Incident Clustering Overlap",
        "Retrieval Relevance@3",
    ]
    metric_values = [float(metrics_json[name]) for name in metric_names]
    ax1.bar(pretty_labels, metric_values, color="#43aa8b")
    ax1.set_ylim(0, 1.0)
    ax1.set_title("Synthetic Ground-Truth Evaluation")
    ax1.tick_params(axis="x", rotation=35)
    ax1.text(
        0.02,
        -0.22,
        "Metrics are approximate and evaluated against simulated incident windows.",
        transform=ax1.transAxes,
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "#f2f2f2", "edgecolor": "#cccccc"},
        clip_on=False,
    )

    ax2.hist(risk_df["risk_score"], bins=6, color="#577590", edgecolor="white")
    ax2.set_title("Risk Score Distribution")
    ax2.set_xlabel("Risk Score")
    return save_figure(fig, "model_evaluation.png")


def save_figure(fig: plt.Figure, filename: str) -> Path:
    path = ASSETS_DIR / filename
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Screenshot generation failed for {filename}")
    return path


def main() -> None:
    saved = capture_screenshots()
    print("Saved screenshots:", ", ".join(path.name for path in saved))


if __name__ == "__main__":
    main()
