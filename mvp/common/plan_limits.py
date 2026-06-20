# mvp/common/plan_limits.py
"""Freemium plan definitions and usage limit enforcement."""
from __future__ import annotations

from typing import Any, Dict
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import text


PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    "free": {
        "max_links": 100,
        "min_scan_frequency_seconds": 3600,  # 1 hour
    },
    "pro": {
        "max_links": 1000,
        "min_scan_frequency_seconds": 900,  # 15 minutes
    },
    "pro_plus": {
        "max_links": 10000,
        "min_scan_frequency_seconds": 60,  # 1 minute
    },
}


def get_tenant_plan(session: Session, tenant_id: UUID) -> str:
    """Return the plan name for a tenant."""
    row = session.execute(
        text("SELECT plan FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    ).fetchone()
    return row[0] if row else "free"


def count_links_for_tenant(session: Session, tenant_id: UUID) -> int:
    """Return total number of links owned by a tenant."""
    row = session.execute(
        text("SELECT COUNT(*) FROM links WHERE tenant_id = :id"),
        {"id": str(tenant_id)},
    ).fetchone()
    return row[0] if row else 0


def count_links_for_project(session: Session, project_id: UUID) -> int:
    """Return number of links in a project."""
    row = session.execute(
        text("SELECT COUNT(*) FROM links WHERE project_id = :id"),
        {"id": str(project_id)},
    ).fetchone()
    return row[0] if row else 0


def get_last_scan_for_project(session: Session, project_id: UUID):
    """Return the most recent scan row for a project."""
    row = session.execute(
        text(
            """
            SELECT scheduled_at, status
            FROM scans
            WHERE project_id = :id
            ORDER BY scheduled_at DESC
            LIMIT 1
            """
        ),
        {"id": str(project_id)},
    ).mappings().fetchone()
    return dict(row) if row else None


def check_link_limit(session: Session, tenant_id: UUID, additional: int = 0) -> tuple[bool, str]:
    """Check if tenant can add more links.

    Returns (allowed, reason).
    """
    plan = get_tenant_plan(session, tenant_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    max_links = limits["max_links"]
    current = count_links_for_tenant(session, tenant_id)
    if current + additional > max_links:
        return False, f"Plan '{plan}' limit exceeded: {current}/{max_links} links. Upgrade to add more."
    return True, ""


def check_scan_frequency(session: Session, project_id: UUID, tenant_id: UUID) -> tuple[bool, str]:
    """Check if enough time has passed since the last scan.

    Returns (allowed, reason).
    """
    from datetime import datetime, timezone

    plan = get_tenant_plan(session, tenant_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    min_freq = limits["min_scan_frequency_seconds"]

    last = get_last_scan_for_project(session, project_id)
    if last and last.get("scheduled_at"):
        elapsed = (datetime.now(timezone.utc) - last["scheduled_at"]).total_seconds()
        if elapsed < min_freq:
            return False, f"Scan rate limited. Please wait {int(min_freq - elapsed)} seconds before next scan."
    return True, ""
