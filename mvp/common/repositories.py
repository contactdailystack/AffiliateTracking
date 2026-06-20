# mvp/common/repositories.py
"""Shared DB operations used by both API and Worker."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_tenant_by_api_key_hash(session: Session, raw_key: str) -> Optional[Dict[str, Any]]:
    """Fetch tenant by verifying a raw API key hash directly in database."""
    from common.auth_utils import _hash_key

    key_hash = _hash_key(raw_key)
    row = session.execute(
        text("SELECT id, name, api_key_hash, plan FROM tenants WHERE api_key_hash = :hash"),
        {"hash": key_hash}
    ).mappings().fetchone()

    return dict(row) if row else None


def list_projects(
    session: Session,
    tenant_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List projects for a tenant."""
    rows = session.execute(
        text(
            """
            SELECT id, tenant_id, name, scan_frequency_seconds, created_at
            FROM projects
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"tenant_id": str(tenant_id), "limit": limit, "offset": offset},
    ).mappings().all()

    return [dict(r) for r in rows]


def create_scan_record(session: Session, tenant_id: UUID, project_id: UUID, status: str = "running") -> UUID:
    """Create a scan row so history can track queued/running/completed scans."""
    import uuid as uuid_mod

    scan_id = uuid_mod.uuid4()
    session.execute(
        text(
            """
            INSERT INTO scans (id, tenant_id, project_id, scheduled_at, status)
            VALUES (:id, :tenant_id, :project_id, NOW(), :status)
            """
        ),
        {
            "id": str(scan_id),
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "status": status,
        },
    )
    session.commit()
    return scan_id


def complete_scan_record(session: Session, scan_id: UUID, status: str = "completed") -> None:
    """Mark a scan as finished."""
    session.execute(
        text(
            """
            UPDATE scans
            SET status = :status, completed_at = NOW()
            WHERE id = :scan_id
            """
        ),
        {"scan_id": str(scan_id), "status": status},
    )
    session.commit()


def get_project_by_id(session: Session, project_id: UUID) -> Optional[Dict[str, Any]]:
    """Fetch a single project by its UUID."""
    row = session.execute(
        text(
            """
            SELECT id, tenant_id, name, scan_frequency_seconds, created_at
            FROM projects
            WHERE id = :project_id
            """
        ),
        {"project_id": str(project_id)},
    ).mappings().fetchone()

    return dict(row) if row else None


def get_links_by_project(session: Session, project_id: UUID) -> List[Dict[str, Any]]:
    """Return all links for a project joined with their merchant rules."""
    rows = session.execute(
        text(
            """
            SELECT
                l.id AS link_id,
                l.tenant_id,
                l.project_id,
                l.merchant_rule_id,
                l.original_url,
                l.source_label,
                mr.merchant_name,
                mr.required_tracking_keys
            FROM links l
            JOIN merchant_rules mr ON mr.id = l.merchant_rule_id
            WHERE l.project_id = :project_id
            """
        ),
        {"project_id": str(project_id)},
    ).mappings().all()

    return [dict(r) for r in rows]


def upsert_issue(
    session: Session,
    tenant_id: UUID,
    project_id: UUID,
    link_id: UUID,
    merchant_rule_id: UUID,
    issue_type: str,
    severity: int,
    evidence: Dict[str, Any],
) -> bool:
    """Upsert an issue. Returns True if a *new* row was inserted, False if updated."""
    import uuid as uuid_mod

    issue_id = uuid_mod.uuid4()

    # Try insert first. On conflict (same tenant/project/link/type), just update last_seen_at.
    result = session.execute(
        text(
            """
            INSERT INTO issues (
                id, tenant_id, project_id, link_id, merchant_rule_id,
                issue_type, severity, status, evidence,
                first_seen_at, last_seen_at
            )
            VALUES (
                :id, :tenant_id, :project_id, :link_id, :merchant_rule_id,
                :issue_type, :severity, 'open', :evidence,
                NOW(), NOW()
            )
            ON CONFLICT (tenant_id, project_id, link_id, issue_type)
            DO UPDATE SET
                last_seen_at = NOW(),
                severity = EXCLUDED.severity,
                evidence = EXCLUDED.evidence,
                status = 'open'
            RETURNING (xmax = 0) AS was_inserted
            """
        ),
        {
            "id": str(issue_id),
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "link_id": str(link_id),
            "merchant_rule_id": str(merchant_rule_id),
            "issue_type": issue_type,
            "severity": severity,
            "evidence": evidence,
        },
    )

    row = result.fetchone()
    session.commit()
    was_inserted = bool(row[0]) if row else False
    return was_inserted


def create_issue_event(
    session: Session,
    tenant_id: UUID,
    issue_id: UUID,
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    """Append an event to an issue's audit trail."""
    import uuid as uuid_mod

    session.execute(
        text(
            """
            INSERT INTO issue_events (id, tenant_id, issue_id, event_type, payload, created_at)
            VALUES (:id, :tenant_id, :issue_id, :event_type, :payload, NOW())
            """
        ),
        {
            "id": str(uuid_mod.uuid4()),
            "tenant_id": str(tenant_id),
            "issue_id": str(issue_id),
            "event_type": event_type,
            "payload": payload,
        },
    )
    session.commit()


def get_open_issues_by_project(
    session: Session, project_id: UUID
) -> List[Dict[str, Any]]:
    """Return all currently open issues for a project (used for auto-resolve logic)."""
    rows = session.execute(
        text(
            """
            SELECT id, tenant_id, project_id, link_id, issue_type
            FROM issues
            WHERE project_id = :project_id AND status = 'open'
            """
        ),
        {"project_id": str(project_id)},
    ).mappings().all()

    return [dict(r) for r in rows]


def get_tenant_subscription(session: Session, tenant_id: UUID) -> Optional[Dict[str, Any]]:
    """Return the subscription row for a tenant."""
    row = session.execute(
        text(
            """
            SELECT tenant_id, plan, status, stripe_customer_id, stripe_subscription_id,
                   current_period_start, current_period_end
            FROM subscriptions
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": str(tenant_id)},
    ).mappings().fetchone()

    return dict(row) if row else None


def resolve_issue(
    session: Session,
    issue_id: UUID,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    """Mark an open issue as resolved and record an event."""
    session.execute(
        text(
            """
            UPDATE issues
            SET status = 'resolved', resolved_at = NOW(), evidence = COALESCE(:evidence, evidence)
            WHERE id = :issue_id
            """
        ),
        {"issue_id": str(issue_id), "evidence": evidence or {}},
    )
    session.commit()


def get_issue_by_id(session: Session, issue_id: UUID) -> Optional[Dict[str, Any]]:
    """Fetch a single issue by its UUID."""
    row = session.execute(
        text(
            """
            SELECT
                i.id,
                i.tenant_id,
                i.project_id,
                i.link_id,
                i.merchant_rule_id,
                i.issue_type,
                i.severity,
                i.status,
                i.evidence,
                i.first_seen_at,
                i.last_seen_at,
                i.resolved_at
            FROM issues i
            WHERE i.id = :issue_id
            """
        ),
        {"issue_id": str(issue_id)},
    ).mappings().fetchone()

    return dict(row) if row else None


def list_issues(
    session: Session,
    project_id: UUID,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List issues for a project with optional status filter."""
    sql = """
        SELECT
            i.id,
            i.tenant_id,
            i.project_id,
            i.link_id,
            i.merchant_rule_id,
            i.issue_type,
            i.severity,
            i.status,
            i.evidence,
            i.first_seen_at,
            i.last_seen_at,
            i.resolved_at
        FROM issues i
        WHERE i.project_id = :project_id
    """
    params: Dict[str, Any] = {"project_id": str(project_id), "limit": limit, "offset": offset}

    if status:
        sql += " AND i.status = :status"
        params["status"] = status

    sql += " ORDER BY i.last_seen_at DESC LIMIT :limit OFFSET :offset"

    rows = session.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]
