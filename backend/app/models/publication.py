from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.models.enums import PRIVACY_LEVELS, PublicationMode, PublicationStatus, sql_in


class Publication(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_publications_idempotency"),
        CheckConstraint(f"status IN ({sql_in(PublicationStatus)})", name="status_valid"),
        CheckConstraint(f"mode IN ({sql_in(PublicationMode)})", name="mode_valid"),
        CheckConstraint(f"privacy_level IN ({sql_in(PRIVACY_LEVELS)})", name="privacy_valid"),
        CheckConstraint("char_length(title) <= 2200", name="title_length"),
        Index("ix_publications_user_id_created_at", "user_id", "created_at"),
        Index("ix_publications_account_id_status", "account_id", "status"),
        Index("ix_publications_status_updated_at", "status", "updated_at"),
        Index("ix_publications_media_id", "media_id"),
        # a TikTok publish_id may belong to a single publication only
        Index(
            "uq_publications_tiktok_publish_id",
            "tiktok_publish_id",
            unique=True,
            postgresql_where="tiktok_publish_id IS NOT NULL",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connected_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default=PublicationMode.DIRECT_POST.value)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=PublicationStatus.QUEUED.value)

    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    privacy_level: Mapped[str] = mapped_column(String(32), nullable=False)
    disable_comment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disable_duet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disable_stitch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    brand_content_toggle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    brand_organic_toggle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_aigc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cover_timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tiktok_publish_id: Mapped[str | None] = mapped_column(String(128))
    upload_url_enc: Mapped[str | None] = mapped_column(Text)
    chunk_size: Mapped[int | None] = mapped_column(BigInteger)
    total_chunks: Mapped[int | None] = mapped_column(Integer)
    uploaded_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    tiktok_post_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)))

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # a worker holding the lease is actively processing; an expired lease means it died
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fail_reason: Mapped[str | None] = mapped_column(String(64))
    fail_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicationEvent(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "publication_events"
    __table_args__ = (Index("ix_publication_events_publication_id_created_at", "publication_id", "created_at"),)

    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AuditLog(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
