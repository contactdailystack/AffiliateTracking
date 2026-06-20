# mvp/common/email_alert.py
"""MVP-lite email alerting: send plain-text email when an issue is created.

SMTP config is read from environment variables (already wired in docker-compose.yml).
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from typing import List, Optional

import logging

logger = logging.getLogger(__name__)


SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "mvp@example.com")
ALERT_RECIPIENTS = os.getenv("ALERT_RECIPIENTS", "")


def _is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def send_issue_alert(
    issue_type: str,
    severity: int,
    original_url: str,
    final_url: Optional[str],
    missing_params: List[str],
    redirect_chain: List[dict],
    error_message: Optional[str],
) -> bool:
    """Send a plain-text email alert for a newly created issue.

    Returns True if the email was sent (or if SMTP is not configured and we
    silently skip), False on a genuine send failure.
    """
    if not _is_configured():
        logger.info("SMTP not configured; skipping email alert.")
        return True

    recipients = [r.strip() for r in ALERT_RECIPIENTS.split(",") if r.strip()]
    if not recipients:
        logger.warning("ALERT_RECIPIENTS not set; skipping email alert.")
        return True

    subject = f"[AffiliateMVP] Issue Detected: {issue_type} (Severity {severity})"

    body_lines = [
        "Affiliate Tracking Integrity Alert",
        "=" * 40,
        f"Issue Type : {issue_type}",
        f"Severity   : {severity}",
        f"Original URL: {original_url}",
        f"Final URL  : {final_url or 'N/A'}",
    ]

    if missing_params:
        body_lines.append(f"Missing Tracking Params: {', '.join(missing_params)}")

    if error_message:
        body_lines.append(f"Error Message: {error_message}")

    if redirect_chain:
        body_lines.append("")
        body_lines.append("Redirect Chain:")
        for i, hop in enumerate(redirect_chain, 1):
            body_lines.append(f"  {i}. {hop.get('url', 'N/A')} (HTTP {hop.get('status_code', '?')})")

    body_lines.append("")
    body_lines.append("-- AffiliateMVP Alert Bot")

    body = "\n".join(body_lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(EMAIL_FROM, recipients, msg.as_string())
        logger.info("Email alert sent to %s for issue_type=%s", recipients, issue_type)
        return True
    except Exception as exc:
        logger.exception("Failed to send email alert: %s", exc)
        return False
