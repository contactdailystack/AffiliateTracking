# mvp/common/discord_alert.py
"""MVP-lite Discord alerting: send a message to a Discord channel via Webhook when an issue is created."""
from __future__ import annotations

import os
import logging
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_ENABLED = bool(DISCORD_WEBHOOK_URL)


def send_discord_issue_alert(
    issue_type: str,
    severity: int,
    original_url: str,
    final_url: Optional[str],
    missing_params: List[str],
    error_message: Optional[str],
) -> bool:
    """Send a Discord webhook alert for a newly created issue."""
    if not DISCORD_ENABLED:
        logger.info("Discord webhook not configured; skipping alert.")
        return True

    # Color mapping: High severity (red), Medium severity (orange), Low severity (yellow)
    color = 15158332 if severity >= 3 else (15105570 if severity == 2 else 16776960)

    # Construct Discord Rich Embed payload
    embed = {
        "title": "🚨 Affiliate Tracking Issue Detected",
        "description": "An issue impacting potential commission has been detected during a scan.",
        "color": color,
        "fields": [
            {"name": "Issue Type", "value": f"`{issue_type}`", "inline": True},
            {"name": "Severity", "value": f"`Level {severity}`", "inline": True},
            {"name": "Original URL", "value": original_url, "inline": False},
        ],
        "footer": {"text": "AffiliateMVP Alert Bot"},
    }

    if final_url:
        embed["fields"].append({"name": "Final Redirect URL", "value": final_url, "inline": False})
    if missing_params:
        embed["fields"].append({"name": "Missing Tracking Params", "value": ", ".join([f"`{p}`" for p in missing_params]), "inline": False})
    if error_message:
        embed["fields"].append({"name": "Error Details", "value": f"```{error_message}```", "inline": False})

    payload = {
        "username": "AffiliateMVP Monitor",
        "embeds": [embed],
    }

    try:
        r = httpx.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        r.raise_for_status()
        logger.info("Discord webhook alert sent for issue_type=%s", issue_type)
        return True
    except Exception as exc:
        logger.exception("Failed to send Discord alert: %s", exc)
        return False
