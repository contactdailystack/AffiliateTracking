from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_api_key_tenant
from ..db import SessionLocal
from ..schemas import WordPressSyncRequest, WordPressSyncResponse
from .. import services

router = APIRouter(prefix="/integrations/wordpress", tags=["integrations"])


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sync-links", response_model=WordPressSyncResponse)
def sync_links(
    payload: WordPressSyncRequest,
    tenant_id=Depends(get_api_key_tenant),
    session: Session = Depends(get_session),
):
    try:
        services.ensure_project_ownership(session, tenant_id, payload.project_id)
        inserted = services.import_links(
            session=session,
            tenant_id=tenant_id,
            project_id=payload.project_id,
            links=[
                {
                    "merchant_name": payload.merchant_name,
                    "original_url": item.original_url,
                    "source_label": item.source_label,
                }
                for item in payload.links
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return WordPressSyncResponse(inserted=inserted, project_id=payload.project_id)
