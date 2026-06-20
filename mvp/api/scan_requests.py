from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field
from uuid import UUID


class ScanVariantRequest(BaseModel):
    name: str = Field(default="default")
    user_agent: Optional[str] = None
    accept_language: Optional[str] = None
    geo_label: Optional[str] = None
    proxy_url: Optional[str] = None
    device: Literal["desktop", "mobile"] = "desktop"


class StartScanRequest(BaseModel):
    project_id: UUID
    scan_variants: list[ScanVariantRequest] = Field(default_factory=list)
