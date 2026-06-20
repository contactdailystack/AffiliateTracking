# mvp/api/routers/auth.py
"""Authentication endpoints: register, login, me."""
from __future__ import annotations

import os
from uuid import UUID
import uuid as uuid_mod

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..db import SessionLocal
from .. import repositories as api_repos
from ..schemas import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    UserProfileResponse,
)
from ...common.jwt_utils import hash_password, verify_password, create_access_token, decode_access_token
from ...common.supabase_auth import is_supabase_mode

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/config")
def config():
    return {
        "auth_mode": "supabase" if is_supabase_mode() else "local",
        "supabase_mode": is_supabase_mode(),
        "local_auth_enabled": not is_supabase_mode(),
        "supabase_ready": bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_ANON_KEY", "").strip()),
    }


def _reject_local_auth_when_supabase_mode() -> None:
    if is_supabase_mode():
        raise HTTPException(
            status_code=503,
            detail="Local auth is disabled when AUTH_MODE=supabase",
        )


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


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
):
    """Dependency: extract user from Bearer JWT."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id and not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    if is_supabase_mode() and email:
        api_repos.bootstrap_supabase_identity(
            session=session,
            user_id=str(user_id or email),
            email=email,
            full_name=(payload.get("user_metadata") or {}).get("full_name", "") if isinstance(payload.get("user_metadata"), dict) else "",
        )

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


@router.post("/register", response_model=RegisterResponse)
def register(payload: RegisterRequest, session: Session = Depends(get_session)):
    """Register a new tenant + user. Returns JWT access token."""
    _reject_local_auth_when_supabase_mode()
    # Check if email already exists
    existing = session.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": payload.email.lower().strip()},
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    tenant_id = uuid_mod.uuid4()
    user_id = uuid_mod.uuid4()
    tenant_name = payload.full_name or payload.email.split("@")[0]

    # Generate API key for backward compatibility
    from ...common.auth_utils import generate_api_key
    raw_key, key_hash = generate_api_key()

    # Create tenant
    api_repos.upsert_tenant(session, tenant_id, tenant_name, api_key_hash=key_hash, plan="free")

    # Create user
    session.execute(
        text(
            """
            INSERT INTO users (id, tenant_id, email, password_hash, full_name)
            VALUES (:id, :tenant_id, :email, :password_hash, :full_name)
            """
        ),
        {
            "id": str(user_id),
            "tenant_id": str(tenant_id),
            "email": payload.email.lower().strip(),
            "password_hash": hash_password(payload.password),
            "full_name": payload.full_name or "",
        },
    )
    session.commit()

    # Create default subscription row
    session.execute(
        text(
            """
            INSERT INTO subscriptions (id, tenant_id, plan, status)
            VALUES (:id, :tenant_id, 'free', 'active')
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"id": str(uuid_mod.uuid4()), "tenant_id": str(tenant_id)},
    )
    session.commit()

    token = create_access_token(str(user_id), str(tenant_id), payload.email)
    return RegisterResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        tenant_id=tenant_id,
        email=payload.email,
        plan="free",
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    """Login with email + password. Returns JWT access token."""
    _reject_local_auth_when_supabase_mode()
    row = session.execute(
        text(
            """
            SELECT u.id, u.tenant_id, u.email, u.password_hash, u.full_name, u.is_active, t.plan
            FROM users u
            JOIN tenants t ON t.id = u.tenant_id
            WHERE u.email = :email
            """
        ),
        {"email": payload.email.lower().strip()},
    ).mappings().fetchone()

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="User account is deactivated")

    token = create_access_token(str(row["id"]), str(row["tenant_id"]), row["email"])
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=row["id"],
        tenant_id=row["tenant_id"],
        email=row["email"],
        plan=row["plan"],
    )


@router.get("/me", response_model=UserProfileResponse)
def me(current_user: dict = Depends(get_current_user)):
    """Get current logged-in user profile."""
    return UserProfileResponse(
        id=current_user["id"],
        tenant_id=current_user["tenant_id"],
        email=current_user["email"],
        full_name=current_user.get("full_name") or "",
        plan=current_user["plan"],
        tenant_name=current_user.get("tenant_name") or "",
    )
