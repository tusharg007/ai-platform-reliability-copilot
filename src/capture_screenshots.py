"""Generate dashboard-style PNG assets from pipeline outputs."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.config import ASSETS_DIR, PREDICTIONS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR, ensure_project_dirs


def capture_screenshots() -> list[Path]:
    ensure_project_dirs()
    metrics_df = pd.read_csv(PROCESSED_DATA_DIR / "service_hourly_metrics.csv")
    alerts_df = pd.read_csv(PREDICTIONS_DIR / "reliability_alerts.csv")
    incidents_df = pd.read_csv(PREDICTIONS_DIR / "incidents.csv")
    risk_df = pd.read_csv(PREDICTIONS_DIR / "service_risk_scores.csv")

    metrics_df["hour"] = pd.to_datetime(metrics_df["hour"], utc=True)
    alerts_df["timestamp"] = pd.to_datetime(alerts_df["timestamp"], utc=True)
    incidents_df["start_time"] = pd.to_datetime(incidents_df["start_time"], utc=True)
    incidents_df["end_time"] = pd.to_datetime(incidents_df["end_time"], utc=True)

    saved_paths = [
        save_overview(metrics_df, risk_df),
        save_service_health(risk_df),
        save_anomaly_detection(alerts_df),
        save_incident_timeline(incidents_df),
        save_copilot_placeholder(),
        save_model_evaluation(),
    ]
    return saved_paths


def save_overview(metrics_df: pd.DataFrame, risk_df: pd.DataFrame) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    latest = metrics_df.sort_values("hour").groupby("service_name").tail(1)
    axes[0].bar(latest["service_name"], latest["error_rate"] * 100, color="#c24f3d")
    axes[0].set_title("Latest Error Rate by Service")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].set_ylabel("Error Rate (%)")
    axes[1].bar(risk_df["service_name"], risk_df["risk_score"], color="#1f6f8b")
    axes[1].set_title("Reliability Risk Score")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].set_ylabel("Risk Score")
    return save_figure(fig, "dashboard_overview.png")


def save_service_health(risk_df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = risk_df["risk_band"].map({"Low": "#4caf50", "Medium": "#ffb300", "High": "#ef6c00", "Critical": "#c62828"})
    ax.barh(risk_df["service_name"], risk_df["risk_score"], color=colors)
    ax.set_title("Service Health Risk Bands")
    ax.set_xlabel("Risk Score")
    return save_figure(fig, "service_health.png")


def save_anomaly_detection(alerts_df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))
    counts = alerts_df.groupby([alerts_df["timestamp"].dt.date, "severity"]).size().unstack(fill_value=0)
    counts.plot(ax=ax)
    ax.set_title("Reliability Alerts by Day")
    ax.set_xlabel("Date")
    ax.set_ylabel("Alert Count")
    return save_figure(fig, "anomaly_detection.png")


def save_incident_timeline(incidents_df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))
    y_positions = range(len(incidents_df))
    starts = incidents_df["start_time"].map(pd.Timestamp.timestamp)
    ends = incidents_df["end_time"].map(pd.Timestamp.timestamp)
    durations = ends - starts
    ax.barh(list(y_positions), durations, left=starts, color="#5b8c5a")
    ax.set_yticks(list(y_positions))
    ax.set_yticklabels(incidents_df["incident_id"])
    ax.set_title("Incident Timeline")
    ax.set_xlabel("Unix Time Window")
    return save_figure(fig, "incident_timeline.png")


def save_copilot_placeholder() -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.axis("off")
    ax.text(
        0.02,
        0.95,
        "Copilot Assistant",
        fontsize=18,
        fontweight="bold",
        transform=ax.transAxes,
    )
    ax.text(
        0.02,
        0.75,
        "Summary\nLikely cause: deployment regression with downstream timeout propagation.\n\nSupporting evidence\n- Elevated p95 latency\n- High error rate after version change\n- Matching runbook retrieved",
        fontsize=12,
        va="top",
        transform=ax.transAxes,
    )
    return save_figure(fig, "copilot_assistant.png")


def save_model_evaluation() -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.axis("off")
    text = (REPORTS_DIR / "model_evaluation.md").read_text(encoding="utf-8")
    ax.text(0.01, 0.99, text[:1800], va="top", family="monospace", fontsize=10, transform=ax.transAxes)
    return save_figure(fig, "model_evaluation.png")


def save_figure(fig: plt.Figure, filename: str) -> Path:
    path = ASSETS_DIR / filename
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    saved = capture_screenshots()
    print("Saved screenshots:", ", ".join(path.name for path in saved))


if __name__ == "__main__":
    main()
