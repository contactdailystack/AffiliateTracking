from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID

from ..auth import get_current_user_jwt
from ..db import SessionLocal
from ..scan_requests import StartScanRequest
from .. import tasks
from .. import services
from ...common.repositories import create_scan_record
from sqlalchemy import text
from ..rate_limiter import rate_limit

router = APIRouter(prefix="/scans", tags=["scans"])


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _dump_variant(variant):
    dump = getattr(variant, "model_dump", None)
    return dump() if dump else variant.dict()


@router.post("/start", dependencies=[Depends(rate_limit(10, 60))])
def start_scan(
    payload: StartScanRequest,
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    tenant_id = current_user["tenant_id"]
    allowed, reason = services.check_scan_allowed(session, payload.project_id, tenant_id)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    scan_id = create_scan_record(session, tenant_id=tenant_id, project_id=payload.project_id, status="queued")
    job_id = tasks.enqueue_scan_project(
        scan_id=scan_id,
        project_id=payload.project_id,
        scan_variants=[_dump_variant(variant) for variant in payload.scan_variants],
    )
    # MVP: celery send_task returns AsyncResult-like; keep generic.
    return {
        "queued": True,
        "scan_id": str(scan_id),
        "celery_task_id": str(getattr(job_id, "id", job_id)),
    }


@router.get("/history", dependencies=[Depends(rate_limit(60, 60))])
def list_scan_history(
    project_id: UUID = Query(..., description="Project ID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """List scan history for a project."""
    tenant_id = current_user["tenant_id"]
    services.ensure_project_ownership(session, tenant_id, project_id)
    rows = session.execute(
        text(
            """
            SELECT id, tenant_id, project_id, scheduled_at, completed_at, status, created_at
            FROM scans
            WHERE project_id = :project_id
            ORDER BY scheduled_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"project_id": str(project_id), "limit": limit, "offset": offset},
    ).mappings().all()

    items = [dict(r) for r in rows]
    # Count total
    total_row = session.execute(
        text("SELECT COUNT(*) FROM scans WHERE project_id = :project_id"),
        {"project_id": str(project_id)},
    ).fetchone()
    total = total_row[0] if total_row else 0

    return {"items": items, "total": total}


