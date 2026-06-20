from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..schemas import CreateTenantRequest

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("", response_model=CreateTenantResponse)
def create_tenant(
    payload: CreateTenantRequest,
    session: Session = Depends(get_session),
):
    raise HTTPException(
        status_code=410,
        detail="Tenant provisioning is disabled in production; use authenticated bootstrap flows",
    )

