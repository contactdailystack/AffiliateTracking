from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
import uuid


def upsert_tenant(
    session: Session,
    tenant_id: UUID,
    name: str,
    api_key_hash: str | None = "",
    plan: str = "free",
):
    session.execute(
        text(
            "INSERT INTO tenants(id, name, api_key_hash, plan) VALUES(:id, :name, :api_key_hash, :plan) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, api_key_hash = EXCLUDED.api_key_hash, plan = EXCLUDED.plan"
        ),
        {"id": str(tenant_id), "name": name, "api_key_hash": api_key_hash, "plan": plan},
    )
    session.commit()


def get_user_by_email(session: Session, email: str):
    row = session.execute(
        text(
            """
            SELECT u.id, u.tenant_id, u.email, u.full_name, u.is_active, t.plan, t.name as tenant_name
            FROM users u
            JOIN tenants t ON t.id = u.tenant_id
            WHERE u.email = :email
            """
        ),
        {"email": email.lower().strip()},
    ).mappings().fetchone()
    return dict(row) if row else None


def upsert_user(
    session: Session,
    user_id: UUID,
    tenant_id: UUID,
    email: str,
    full_name: str = "",
    password_hash: str = "",
    is_active: bool = True,
):
    session.execute(
        text(
            """
            INSERT INTO users (id, tenant_id, email, password_hash, full_name, is_active)
            VALUES (:id, :tenant_id, :email, :password_hash, :full_name, :is_active)
            ON CONFLICT (email) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                full_name = EXCLUDED.full_name,
                is_active = EXCLUDED.is_active
            """
        ),
        {
            "id": str(user_id),
            "tenant_id": str(tenant_id),
            "email": email.lower().strip(),
            "password_hash": password_hash,
            "full_name": full_name,
            "is_active": is_active,
        },
    )
    session.commit()


def bootstrap_supabase_identity(session: Session, user_id: str, email: str, full_name: str = ""):
    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, f"supabase-tenant:{user_id}")
    try:
        local_user_id = UUID(user_id)
    except Exception:
        local_user_id = uuid.uuid5(uuid.NAMESPACE_URL, f"supabase-user:{user_id}")
    tenant_name = full_name or email.split("@")[0]
    upsert_tenant(session, tenant_id, tenant_name, api_key_hash=None, plan="free")
    upsert_user(
        session=session,
        user_id=local_user_id,
        tenant_id=tenant_id,
        email=email,
        full_name=full_name or tenant_name,
        password_hash="",
        is_active=True,
    )
    return {"tenant_id": tenant_id, "user_id": local_user_id}


def create_project(session: Session, tenant_id: UUID, name: str, scan_frequency_seconds: int) -> UUID:
    # DB will generate UUID in this MVP? schema.sql expects id UUID PRIMARY KEY without default.
    # We'll generate via app side for MVP simplicity.
    import uuid

    project_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO projects(id, tenant_id, name, scan_frequency_seconds) VALUES(:id, :tenant_id, :name, :freq)"
        ),
        {
            "id": str(project_id),
            "tenant_id": str(tenant_id),
            "name": name,
            "freq": scan_frequency_seconds,
        },
    )
    session.commit()
    return project_id


def upsert_merchant_rule(session: Session, tenant_id: UUID, project_id: UUID, merchant_name: str, required_tracking_keys):
    import uuid

    # upsert by (project_id, merchant_name)
    rule_id = uuid.uuid4()

    # required_tracking_keys will be JSON array of {key, required}
    # Note: we return the generated id for MVP even if it was an update.
    session.execute(
        text(
            "INSERT INTO merchant_rules(id, tenant_id, project_id, merchant_name, required_tracking_keys) "
            "VALUES(:id, :tenant_id, :project_id, :merchant_name, :rtk) "
            "ON CONFLICT (project_id, merchant_name) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, required_tracking_keys = EXCLUDED.required_tracking_keys"
        ),
        {
            "id": str(rule_id),
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "merchant_name": merchant_name,
            "rtk": required_tracking_keys,
        },
    )
    session.commit()
    return rule_id



def import_links(session: Session, tenant_id: UUID, project_id: UUID, links):
    import uuid
    inserted = 0

    # For each link, find merchant_rule_id by (project_id, merchant_name)
    for item in links:
        rule = session.execute(
            text(
                "SELECT id FROM merchant_rules WHERE tenant_id=:tenant_id AND project_id=:project_id AND merchant_name=:merchant_name"
            ),
            {
                "tenant_id": str(tenant_id),
                "project_id": str(project_id),
                "merchant_name": item.merchant_name,
            },
        ).fetchone()

        if rule is None:
            raise ValueError(f"merchant rule not found for merchant_name={item.merchant_name}")

        session.execute(
            text(
                "INSERT INTO links(id, tenant_id, project_id, merchant_rule_id, source_label, original_url) "
                "VALUES(:id, :tenant_id, :project_id, :merchant_rule_id, :source_label, :original_url)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "project_id": str(project_id),
                "merchant_rule_id": str(rule[0]),
                "source_label": item.source_label,
                "original_url": item.original_url,
            },
        )
        inserted += 1

    session.commit()
    return inserted

