from pydantic import BaseModel, Field
from typing import Any, List, Optional
from uuid import UUID
from datetime import datetime


# ------------------------------------------------------------------
# Auth schemas
# ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: UUID
    tenant_id: UUID
    email: str
    plan: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: UUID
    tenant_id: UUID
    email: str
    plan: str


class UserProfileResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    full_name: Optional[str] = None
    plan: str
    tenant_name: Optional[str] = None


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    current_period_end: Optional[str] = None
    stripe_subscription_id: Optional[str] = None


# ------------------------------------------------------------------
# Tenant / Project schemas
# ------------------------------------------------------------------
class CreateTenantRequest(BaseModel):
    name: str


class CreateTenantResponse(BaseModel):
    id: UUID
    name: str
    api_key: str  # raw key shown ONCE at creation
    plan: str = "free"


class CreateProjectRequest(BaseModel):
    tenant_id: UUID
    name: str
    scan_frequency_seconds: int = Field(default=86400, ge=60)


class CreateProjectResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    scan_frequency_seconds: int


class ProjectListItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    scan_frequency_seconds: int
    created_at: Optional[datetime] = None


class ProjectListResponse(BaseModel):
    items: List[ProjectListItem]
    total: int


class MerchantRuleItem(BaseModel):
    key: str
    required: bool = False


class SetMerchantRuleRequest(BaseModel):
    tenant_id: UUID
    project_id: UUID
    merchant_name: str
    required_tracking_keys: List[MerchantRuleItem]


class SetMerchantRuleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    merchant_name: str
    required_tracking_keys: list[Any]


class LinkImportItem(BaseModel):
    merchant_name: str
    original_url: str
    source_label: Optional[str] = None


class ImportLinksRequest(BaseModel):
    tenant_id: UUID
    project_id: UUID
    links: List[LinkImportItem]


class ImportLinksResponse(BaseModel):
    inserted: int


class WordPressSyncRequest(BaseModel):
    project_id: UUID
    merchant_name: str
    links: List[LinkImportItem]


class WordPressSyncResponse(BaseModel):
    inserted: int
    project_id: UUID


# ------------------------------------------------------------------
# Issue schemas
# ------------------------------------------------------------------
class IssueResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    link_id: UUID
    merchant_rule_id: UUID
    issue_type: str
    severity: int
    status: str
    evidence: dict[str, Any]
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    resolved_at: Optional[str] = None


class IssueListResponse(BaseModel):
    items: List[IssueResponse]
    total: int


class ResolveIssueRequest(BaseModel):
    reason: Optional[str] = None


class ResolveIssueResponse(BaseModel):
    id: UUID
    status: str
    resolved_at: Optional[str] = None

