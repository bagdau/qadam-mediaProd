from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.models.enums import AccountStatus, sql_in


class ConnectedAccount(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "provider_account_id", name="uq_connected_accounts_identity"),
        CheckConstraint(f"status IN ({sql_in(AccountStatus)})", name="status_valid"),
        CheckConstraint("provider IN ('tiktok')", name="provider_valid"),
        Index("ix_connected_accounts_user_id_status", "user_id", "status"),
        Index("ix_connected_accounts_access_expires_at", "access_expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="tiktok")
    provider_account_id: Mapped[str] = mapped_column(String(128), nullable=False)  # TikTok open_id
    username: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(256))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    # Fernet ciphertext (see app.core.crypto). NULL once revoked/disconnected.
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AccountStatus.ACTIVE.value)
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthState(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "oauth_states"
    __table_args__ = (
        Index("ix_oauth_states_expires_at", "expires_at"),
        Index("ix_oauth_states_user_id", "user_id"),
    )

    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="tiktok")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
