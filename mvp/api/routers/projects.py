from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID

from ..auth import get_current_user_jwt
from ..db import SessionLocal
from ..schemas import (
    CreateProjectRequest,
    CreateProjectResponse,
    ImportLinksRequest,
    ImportLinksResponse,
    SetMerchantRuleRequest,
    ProjectListItem,
    ProjectListResponse,
)
from .. import services
from ..rate_limiter import rate_limit
from ...common.plan_limits import PLAN_LIMITS, get_tenant_plan

router = APIRouter(prefix="/projects", tags=["projects"])


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=ProjectListResponse, dependencies=[Depends(rate_limit(100, 60))])
def list_projects(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    """List all projects for a given tenant."""
    tenant_id = current_user["tenant_id"]
    rows = services.list_tenant_projects(session, tenant_id, limit, offset)
    items = [ProjectListItem(**dict(r)) for r in rows]
    return ProjectListResponse(items=items, total=len(items))


@router.post("", response_model=CreateProjectResponse, dependencies=[Depends(rate_limit(30, 60))])
def create_project(
    payload: CreateProjectRequest,
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    tenant_id = current_user["tenant_id"]
    if tenant_id != payload.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    plan = get_tenant_plan(session, tenant_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    if payload.scan_frequency_seconds < limits["min_scan_frequency_seconds"]:
        raise HTTPException(
            status_code=429,
            detail=f"Plan '{plan}' requires scan frequency >= {limits['min_scan_frequency_seconds']} seconds",
        )
    pid = services.create_project(
        session=session,
        tenant_id=payload.tenant_id,
        name=payload.name,
        scan_frequency_seconds=payload.scan_frequency_seconds,
    )
    return CreateProjectResponse(
        id=pid,
        tenant_id=payload.tenant_id,
        name=payload.name,
        scan_frequency_seconds=payload.scan_frequency_seconds,
    )


@router.post("/merchant-rules", dependencies=[Depends(rate_limit(30, 60))])
def set_merchant_rule(
    payload: SetMerchantRuleRequest,
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    tenant_id = current_user["tenant_id"]
    if tenant_id != payload.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    services.ensure_project_ownership(session, tenant_id, payload.project_id)

    rule_id = services.set_merchant_rule(
        session=session,
        tenant_id=payload.tenant_id,
        project_id=payload.project_id,
        merchant_name=payload.merchant_name,
        required_tracking_keys=payload.required_tracking_keys,
    )
    return {"merchant_rule_id": rule_id}


@router.post("/import-links", response_model=ImportLinksResponse, dependencies=[Depends(rate_limit(20, 60))])
def import_links(
    payload: ImportLinksRequest,
    current_user: dict = Depends(get_current_user_jwt),
    session: Session = Depends(get_session),
):
    tenant_id = current_user["tenant_id"]
    if tenant_id != payload.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    services.ensure_project_ownership(session, tenant_id, payload.project_id)

    inserted = services.import_links(
        session=session,
        tenant_id=payload.tenant_id,
        project_id=payload.project_id,
        links=payload.links,
    )
    return ImportLinksResponse(inserted=inserted)

