"""Slack alerting integration for the AI Platform Reliability Copilot.

Sends structured alert messages to Slack via incoming webhooks when:
  - A SEV-1 or SEV-2 incident is detected
  - A high-severity anomaly fires (configurable threshold)
  - An incident cluster is formed with blast_radius > 0.5
  - Guardrail violations occur (prompt injection attempts)

Set SLACK_WEBHOOK_URL in .env to enable.
Set ALERT_MIN_SEVERITY=SEV-3 to lower the threshold.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Cooldown: don't re-alert the same service within N seconds
_alert_cooldown: dict[str, float] = {}
_COOLDOWN_SECONDS = 300  # 5 minutes


# ─────────────────────────────────────────────────────────────────────────────
#  Severity ordering for threshold comparisons
# ─────────────────────────────────────────────────────────────────────────────

_SEV_ORDER = {"SEV-1": 4, "SEV-2": 3, "SEV-3": 2, "SEV-4": 1}


def _severity_meets_threshold(severity: str, min_severity: str) -> bool:
    return _SEV_ORDER.get(severity, 0) >= _SEV_ORDER.get(min_severity, 0)


def _is_cooling_down(key: str) -> bool:
    last = _alert_cooldown.get(key, 0.0)
    return (time.time() - last) < _COOLDOWN_SECONDS


def _mark_alerted(key: str) -> None:
    _alert_cooldown[key] = time.time()


# ─────────────────────────────────────────────────────────────────────────────
#  Slack Payload Builder
# ─────────────────────────────────────────────────────────────────────────────

_SEV_EMOJI = {
    "SEV-1": "🔴",
    "SEV-2": "🟠",
    "SEV-3": "🟡",
    "SEV-4": "🟢",
}
_SEV_COLOR = {
    "SEV-1": "#E01E5A",
    "SEV-2": "#FF9800",
    "SEV-3": "#F4C430",
    "SEV-4": "#2EB67D",
}


def _build_incident_payload(
    service_name: str,
    region: str | None,
    severity: str,
    title: str,
    summary: str,
    risk_score: float,
    evidence: list[str],
    actions: list[str],
    root_cause: str | None = None,
    mttr_minutes: int | None = None,
) -> dict:
    """Build a rich Slack Block Kit message payload."""
    emoji = _SEV_EMOJI.get(severity, "⚠️")
    color = _SEV_COLOR.get(severity, "#888888")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    scope = f"{service_name} / {region}" if region else service_name

    top_actions = actions[:4]  # Keep Slack message concise
    evidence_text = "\n".join(f"• {e}" for e in evidence[:5])
    actions_text = "\n".join(f"{i+1}. {a}" for i, a in enumerate(top_actions))

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {severity} — {title}", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Service*\n`{scope}`"},
                {"type": "mrkdwn", "text": f"*Severity*\n{emoji} `{severity}`"},
                {"type": "mrkdwn", "text": f"*Risk Score*\n`{risk_score:.3f}`"},
                {"type": "mrkdwn", "text": f"*Est. MTTR*\n`{mttr_minutes or '?'} min`"},
            ],
        },
    ]

    if root_cause:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Root Cause*\n{root_cause}"},
        })

    blocks += [
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Evidence*\n{evidence_text}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Immediate Actions*\n{actions_text}"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"AI Platform Reliability Copilot v2.0 | {ts}"},
            ],
        },
    ]

    return {
        "attachments": [
            {
                "color": color,
                "blocks": blocks,
                "fallback": f"{emoji} {severity} — {title} | {scope} | Risk: {risk_score:.3f}",
            }
        ]
    }


def _build_anomaly_payload(
    service_name: str,
    region: str | None,
    metric_name: str,
    observed_value: float,
    baseline_value: float,
    severity: str,
) -> dict:
    """Build a compact anomaly alert payload."""
    emoji = _SEV_EMOJI.get(severity, "⚠️")
    color = _SEV_COLOR.get(severity, "#888888")
    scope = f"{service_name}/{region}" if region else service_name

    return {
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"{emoji} *Anomaly Detected* | `{scope}`\n"
                                f"*Metric:* `{metric_name}` | "
                                f"*Observed:* `{observed_value:.2f}` | "
                                f"*Baseline:* `{baseline_value:.2f}` | "
                                f"*Severity:* `{severity}`"
                            ),
                        },
                    }
                ],
                "fallback": f"{emoji} Anomaly: {metric_name} = {observed_value:.2f} (baseline {baseline_value:.2f}) in {scope}",
            }
        ]
    }


def _build_cluster_payload(cluster: dict) -> dict:
    """Build a cluster alert payload."""
    svc = cluster.get("centroid_service", "unknown")
    err = cluster.get("centroid_error_type", "unknown")
    blast = cluster.get("blast_radius", 0.0)
    count = cluster.get("member_count", 0)
    affected_svcs = ", ".join(cluster.get("affected_services", []))
    affected_rgns = ", ".join(cluster.get("affected_regions", []))

    return {
        "attachments": [
            {
                "color": "#E01E5A" if blast > 0.6 else "#FF9800",
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"🔗 Incident Cluster Detected — {cluster.get('cluster_id')}", "emoji": True},
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Primary Service*\n`{svc}`"},
                            {"type": "mrkdwn", "text": f"*Error Type*\n`{err}`"},
                            {"type": "mrkdwn", "text": f"*Blast Radius*\n`{blast:.2f}`"},
                            {"type": "mrkdwn", "text": f"*Signals Clustered*\n`{count}`"},
                            {"type": "mrkdwn", "text": f"*Affected Services*\n{affected_svcs}"},
                            {"type": "mrkdwn", "text": f"*Affected Regions*\n{affected_rgns}"},
                        ],
                    },
                ],
                "fallback": f"🔗 Incident cluster: {svc} / {err} — blast_radius={blast:.2f}, {count} signals",
            }
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Sender
# ─────────────────────────────────────────────────────────────────────────────

def _send_to_slack(payload: dict, webhook_url: str) -> bool:
    """POST a payload to a Slack incoming webhook URL. Returns True on success."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.read().decode() == "ok"
            if not ok:
                logger.warning("Slack returned non-ok response")
            return ok
    except Exception as exc:
        logger.warning("Slack send failed: %s", exc)
        return False


def _get_webhook() -> str | None:
    from backend.utils.config import get_settings
    return get_settings().slack_webhook_url


def _get_min_severity() -> str:
    from backend.utils.config import get_settings
    return get_settings().alert_min_severity


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def alert_incident(
    service_name: str,
    region: str | None,
    severity: str,
    title: str,
    summary: str,
    risk_score: float,
    evidence: list[str],
    actions: list[str],
    root_cause: str | None = None,
    mttr_minutes: int | None = None,
) -> bool:
    """Send a Slack incident alert (subject to severity threshold and cooldown).

    Returns True if the alert was sent, False if skipped or failed.
    """
    webhook = _get_webhook()
    if not webhook:
        return False

    if not _severity_meets_threshold(severity, _get_min_severity()):
        logger.debug("Alert skipped: %s below threshold %s", severity, _get_min_severity())
        return False

    cooldown_key = f"incident:{service_name}:{region or 'all'}"
    if _is_cooling_down(cooldown_key):
        logger.debug("Alert skipped: cooldown active for %s", cooldown_key)
        return False

    payload = _build_incident_payload(
        service_name=service_name,
        region=region,
        severity=severity,
        title=title,
        summary=summary,
        risk_score=risk_score,
        evidence=evidence,
        actions=actions,
        root_cause=root_cause,
        mttr_minutes=mttr_minutes,
    )
    sent = _send_to_slack(payload, webhook)
    if sent:
        _mark_alerted(cooldown_key)
        logger.info("Slack alert sent: %s %s/%s risk=%.3f", severity, service_name, region, risk_score)
    return sent


def alert_anomaly(
    service_name: str,
    region: str | None,
    metric_name: str,
    observed_value: float,
    baseline_value: float,
    severity: str = "high",
) -> bool:
    """Send a Slack anomaly alert (only for high severity anomalies)."""
    webhook = _get_webhook()
    if not webhook:
        return False
    if severity != "high":
        return False  # Only alert on high-severity anomalies

    sev_label = "SEV-2"
    if not _severity_meets_threshold(sev_label, _get_min_severity()):
        return False

    cooldown_key = f"anomaly:{service_name}:{metric_name}"
    if _is_cooling_down(cooldown_key):
        return False

    payload = _build_anomaly_payload(
        service_name, region, metric_name, observed_value, baseline_value, severity
    )
    sent = _send_to_slack(payload, webhook)
    if sent:
        _mark_alerted(cooldown_key)
    return sent


def alert_cluster(cluster: dict) -> bool:
    """Send a Slack cluster alert when blast_radius > 0.4."""
    webhook = _get_webhook()
    if not webhook:
        return False

    blast = cluster.get("blast_radius", 0.0)
    if blast < 0.4:
        return False

    cooldown_key = f"cluster:{cluster.get('cluster_id', 'unknown')}"
    if _is_cooling_down(cooldown_key):
        return False

    payload = _build_cluster_payload(cluster)
    sent = _send_to_slack(payload, webhook)
    if sent:
        _mark_alerted(cooldown_key)
    return sent


def send_test_alert() -> bool:
    """Send a test ping to verify the Slack webhook is working."""
    webhook = _get_webhook()
    if not webhook:
        logger.warning("SLACK_WEBHOOK_URL not set — test alert skipped")
        return False

    payload = {
        "text": "✅ *AI Platform Reliability Copilot* — Slack integration is working! "
                "You will receive incident alerts here."
    }
    sent = _send_to_slack(payload, webhook)
    if sent:
        logger.info("Slack test alert sent successfully")
    else:
        logger.error("Slack test alert FAILED — check SLACK_WEBHOOK_URL")
    return sent
