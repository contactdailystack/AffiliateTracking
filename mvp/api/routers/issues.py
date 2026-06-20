from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from uuid import UUID
import csv
import io

from ..auth import get_current_user_jwt
from ..db import SessionLocal
from ..schemas import (
    IssueResponse,
    IssueListResponse,
    ResolveIssueRequest,
    ResolveIssueResponse,
)
from .. import services
from ..rate_limiter import rate_limit

router = APIRouter(prefix="/issues", tags=["issues"])


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/export.csv", response_class=PlainTextResponse, dependencies=[Depends(rate_limit(20, 60))])
def export_csv(
    project_id: UUID = Query(..., description="Filter issues by project ID"),
    status: str | None = Query(default=None, description="Filter by status (open / resolved)"),
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """Export issues as CSV."""
    tenant_id = current_user["tenant_id"]
    services.ensure_project_ownership(session, tenant_id, project_id)
    rows = services.list_project_issues(session, project_id, status, limit=2000, offset=0)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "issue_type", "severity", "status", "link_id",
        "first_seen_at", "last_seen_at", "resolved_at",
        "original_url", "final_url", "http_status",
        "missing_params", "error_message"
    ])
    for r in rows:
        ev = r.get("evidence") or {}
        writer.writerow([
            r.get("id"), r.get("issue_type"), r.get("severity"), r.get("status"), r.get("link_id"),
            r.get("first_seen_at"), r.get("last_seen_at"), r.get("resolved_at"),
            ev.get("original_url", ""), ev.get("final_url", ""), ev.get("http_status", ""),
            "; ".join(ev.get("missing_params", [])), ev.get("error_message", "")
        ])
    output.seek(0)
    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=issues.csv"}
    )


@router.get("", response_model=IssueListResponse, dependencies=[Depends(rate_limit(100, 60))])
def list_issues(
    project_id: UUID = Query(..., description="Filter issues by project ID"),
    status: str | None = Query(default=None, description="Filter by status (open / resolved)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """List issues for a given project."""
    tenant_id = current_user["tenant_id"]
    services.ensure_project_ownership(session, tenant_id, project_id)
    rows = services.list_project_issues(session, project_id, status, limit, offset)
    items = [IssueResponse(**dict(r)) for r in rows]
    return IssueListResponse(items=items, total=len(items))


@router.get("/{issue_id}", response_model=IssueResponse, dependencies=[Depends(rate_limit(100, 60))])
def get_issue(
    issue_id: UUID,
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """Get a single issue detail including evidence (redirect chain, missing params, etc.)."""
    tenant_id = current_user["tenant_id"]
    row = services.get_issue(session, issue_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")
    services.ensure_project_ownership(session, tenant_id, row["project_id"])
    return IssueResponse(**dict(row))


@router.patch("/{issue_id}", response_model=ResolveIssueResponse, dependencies=[Depends(rate_limit(50, 60))])
def resolve_issue(
    issue_id: UUID,
    payload: ResolveIssueRequest | None = None,
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """Manually mark an issue as resolved."""
    tenant_id = current_user["tenant_id"]
    row = services.get_issue(session, issue_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")
    if row.get("status") == "resolved":
        raise HTTPException(status_code=400, detail="Issue already resolved")
    services.ensure_project_ownership(session, tenant_id, row["project_id"])

    updated = services.resolve_issue(
        session, issue_id, payload.reason if payload else None
    )
    return ResolveIssueResponse(
        id=issue_id,
        status="resolved",
        resolved_at=updated.get("resolved_at") if updated else None,
    )
