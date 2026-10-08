from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import PRIVACY_LEVELS, PublicationMode


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class PublicationCreate(BaseModel):
    """What the user asked for. Interaction flags use *allow_* semantics and default to off,
    as required by the TikTok Content Sharing Guidelines."""

    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    media_id: uuid.UUID
    mode: PublicationMode = PublicationMode.DIRECT_POST
    title: Annotated[str, Field(max_length=2200)] = ""
    privacy_level: str  # intentionally no default: the user must choose
    allow_comment: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    brand_content_toggle: bool = False   # paid partnership
    brand_organic_toggle: bool = False   # promoting own business
    is_aigc: bool = False
    cover_timestamp_ms: Annotated[int, Field(ge=0, le=3_600_000)] = 0
    music_usage_confirmed: bool = False
    allow_duplicate: bool = False

    @field_validator("privacy_level")
    @classmethod
    def _privacy(cls, value: str) -> str:
        if value not in PRIVACY_LEVELS:
            raise ValueError("Недопустимый уровень приватности")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if utf16_len(value) > 2200:
            raise ValueError("Описание не должно превышать 2200 символов (UTF-16)")
        return value

    @model_validator(mode="after")
    def _brand(self) -> PublicationCreate:
        if self.mode == PublicationMode.DIRECT_POST and not self.music_usage_confirmed:
            raise ValueError("Подтвердите согласие с Music Usage Confirmation TikTok")
        return self


class PublicationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    type: str
    from_status: str | None
    to_status: str | None
    message: str
    details: dict | None


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    media_id: uuid.UUID
    mode: str
    status: str
    title: str
    privacy_level: str
    disable_comment: bool
    disable_duet: bool
    disable_stitch: bool
    brand_content_toggle: bool
    brand_organic_toggle: bool
    is_aigc: bool
    tiktok_publish_id: str | None
    tiktok_post_ids: list[str] | None
    uploaded_bytes: int
    attempts: int
    fail_reason: str | None
    fail_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PublicationDetail(PublicationOut):
    events: list[PublicationEventOut]
    media_filename: str | None = None
    media_size_bytes: int | None = None
    account_username: str | None = None


class PublicationPage(BaseModel):
    items: list[PublicationOut]
    total: int
    limit: int
    offset: int


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_duplicate_risk: bool = False
