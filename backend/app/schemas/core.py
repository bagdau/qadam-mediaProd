from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    created_at: datetime
    last_login_at: datetime | None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=120)


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    current: bool = False


class AccountOut(BaseModel):
    """Public view of a connected account. Token fields are intentionally absent."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    provider_account_id: str
    username: str | None
    display_name: str | None
    avatar_url: str | None
    scopes: list[str]
    status: str
    last_error: str | None
    connected_at: datetime
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    last_refreshed_at: datetime | None
    disconnected_at: datetime | None


class CreatorInfoOut(BaseModel):
    username: str
    nickname: str
    avatar_url: str | None
    privacy_level_options: list[str]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_video_post_duration_sec: int | None


class OAuthStartOut(BaseModel):
    authorization_url: str


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    duration_seconds: float | None
    sha256: str
    status: str
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    action: str
    entity_type: str | None
    entity_id: str | None
    ip_address: str | None
    details: dict | None


class AuditPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int


class MetaOut(BaseModel):
    tiktok_configured: bool
    tiktok_client_audited: bool
    scopes: list[str]
    max_video_mb: int
    allowed_content_types: list[str]
    allow_registration: bool


class DashboardOut(BaseModel):
    accounts_total: int
    accounts_needing_attention: int
    publications_total: int
    publications_by_status: dict[str, int]
    in_progress: int
    published_last_7_days: int
    daily: list[dict]
    recent: list[dict]
