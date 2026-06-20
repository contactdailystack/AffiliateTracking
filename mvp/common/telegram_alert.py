# mvp/common/telegram_alert.py
"""MVP-lite Telegram alerting: send a message to a Telegram chat when an issue is created."""
from __future__ import annotations

import os
import logging
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram_issue_alert(
    issue_type: str,
    severity: int,
    original_url: str,
    final_url: Optional[str],
    missing_params: List[str],
    error_message: Optional[str],
) -> bool:
    """Send a Telegram message alert for a newly created issue.

    Returns True if the message was sent (or skipped because not configured),
    False on a genuine send failure.
    """
    if not TELEGRAM_ENABLED:
        logger.info("Telegram not configured; skipping alert.")
        return True

    text = (
        f"🚨 <b>Affiliate Issue Detected</b>\n\n"
        f"<b>Type:</b> {issue_type}\n"
        f"<b>Severity:</b> {severity}\n"
        f"<b>Original URL:</b> {original_url}\n"
    )

    if final_url:
        text += f"<b>Final URL:</b> {final_url}\n"
    if missing_params:
        text += f"<b>Missing Params:</b> {', '.join(missing_params)}\n"
    if error_message:
        text += f"<b>Error:</b> {error_message}\n"

    text += "\n— AffiliateMVP Bot"

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        r = httpx.post(url, json=payload, timeout=15)
        r.raise_for_status()
        logger.info("Telegram alert sent for issue_type=%s", issue_type)
        return True
    except Exception as exc:
        logger.exception("Failed to send Telegram alert: %s", exc)
        return False

