from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .db import SessionLocal
from . import repositories as api_repos
from ..common.auth_utils import verify_api_key
from ..common.repositories import get_tenant_by_api_key_hash
from ..common.jwt_utils import decode_access_token
from ..common.supabase_auth import is_supabase_mode

security = HTTPBearer(auto_error=False)


def _coerce_uuid(value):
    try:
        return UUID(str(value))
    except Exception:
        return value


def _normalize_user_row(row: dict) -> dict:
    data = dict(row)
    if data.get("id") is not None:
        data["id"] = _coerce_uuid(data["id"])
    if data.get("tenant_id") is not None:
        data["tenant_id"] = _coerce_uuid(data["tenant_id"])
    return data


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_api_key_tenant(
    x_api_key: str = Header(default=None, alias="X-API-Key"),
    session: Session = Depends(get_session),
) -> UUID:
    """Verify the raw API key against the hashed key in the DB and return the tenant UUID."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")

    tenant = get_tenant_by_api_key_hash(session, x_api_key)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return UUID(str(tenant["id"]))


def get_current_user_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> dict:
    """Verify JWT Bearer token and return user dict with tenant_id."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    email = payload.get("email")
    if not user_id and not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    if is_supabase_mode() and email:
        api_repos.bootstrap_supabase_identity(
            session=session,
            user_id=str(user_id or email),
            email=email,
            full_name=payload.get("user_metadata", {}).get("full_name", "") if isinstance(payload.get("user_metadata"), dict) else "",
        )

    from sqlalchemy import text
    query = """
        SELECT u.id, u.tenant_id, u.email, u.full_name, u.is_active, t.plan, t.name as tenant_name
        FROM users u
        JOIN tenants t ON t.id = u.tenant_id
    """
    params = {}
    if user_id:
        query += " WHERE u.id = :user_id"
        params["user_id"] = user_id
    else:
        query += " WHERE u.email = :email"
        params["email"] = email

    row = session.execute(text(query), params).mappings().fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="User account is deactivated")

    return _normalize_user_row(row)
