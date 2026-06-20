from uuid import UUID
from sqlalchemy.orm import Session

from . import repositories
from ..common.auth_utils import generate_api_key
from ..common.repositories import list_issues, get_issue_by_id, resolve_issue as repo_resolve_issue
from ..common.plan_limits import check_link_limit, check_scan_frequency


def create_tenant(session: Session, tenant_id: UUID, name: str):
    raw_key, key_hash = generate_api_key()
    repositories.upsert_tenant(session, tenant_id, name, api_key_hash=key_hash, plan="free")
    return raw_key


def create_project(session: Session, tenant_id: UUID, name: str, scan_frequency_seconds: int) -> UUID:
    return repositories.create_project(session, tenant_id, name, scan_frequency_seconds)


def set_merchant_rule(session: Session, tenant_id: UUID, project_id: UUID, merchant_name: str, required_tracking_keys):
    return repositories.upsert_merchant_rule(session, tenant_id, project_id, merchant_name, required_tracking_keys)


def import_links(session: Session, tenant_id: UUID, project_id: UUID, links):
    allowed, reason = check_link_limit(session, tenant_id, additional=len(links))
    if not allowed:
        raise ValueError(reason)
    return repositories.import_links(session, tenant_id, project_id, links)


# ------------------------------------------------------------------
# Project services
# ------------------------------------------------------------------

def list_tenant_projects(session: Session, tenant_id: UUID, limit: int, offset: int) -> list[dict]:
    from ..common.repositories import list_projects
    return list_projects(session, tenant_id, limit, offset)


def get_project(session: Session, project_id: UUID) -> dict | None:
    from ..common.repositories import get_project_by_id
    return get_project_by_id(session, project_id)


def ensure_project_ownership(session: Session, tenant_id: UUID, project_id: UUID) -> dict:
    """Verify that a project belongs to the tenant. Returns project dict or raises ValueError."""
    project = get_project(session, project_id)
    if not project:
        raise ValueError("Project not found")
    if str(project["tenant_id"]) != str(tenant_id):
        raise ValueError("Tenant does not own this project")
    return project


def check_scan_allowed(session: Session, project_id: UUID, tenant_id: UUID) -> tuple[bool, str]:
    """Check both ownership and scan frequency limits."""
    try:
        ensure_project_ownership(session, tenant_id, project_id)
    except ValueError as exc:
        return False, str(exc)
    return check_scan_frequency(session, project_id, tenant_id)


# ------------------------------------------------------------------
# Issue services
# ------------------------------------------------------------------

def list_project_issues(
    session: Session,
    project_id: UUID,
    status: str | None,
    limit: int,
    offset: int,
) -> list[dict]:
    return list_issues(session, project_id, status, limit, offset)


def get_issue(session: Session, issue_id: UUID) -> dict | None:
    return get_issue_by_id(session, issue_id)


def resolve_issue(session: Session, issue_id: UUID, reason: str | None) -> dict | None:
    evidence = {"reason": reason} if reason else {}
    repo_resolve_issue(session, issue_id, evidence)
    return get_issue_by_id(session, issue_id)
