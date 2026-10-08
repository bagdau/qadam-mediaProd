"""Periodic housekeeping (Celery beat): expired sessions/OAuth states, stale media files."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import ACTIVE_STATUSES, MediaAsset, OAuthState, Publication, PublicationStatus, Session
from app.services.media import MediaService

logger = logging.getLogger(__name__)


async def cleanup_auth_rows(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    states = await db.execute(delete(OAuthState).where(OAuthState.expires_at < now - timedelta(days=1)))
    sessions = await db.execute(
        delete(Session).where(
            (Session.expires_at < now - timedelta(days=30)) | (Session.revoked_at < now - timedelta(days=30))
        )
    )
    await db.commit()
    return {"oauth_states": states.rowcount or 0, "sessions": sessions.rowcount or 0}


async def cleanup_media(db: AsyncSession, settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    svc = MediaService(settings)
    now = datetime.now(UTC)
    active = [s.value for s in ACTIVE_STATUSES]
    done = [PublicationStatus.PUBLISHED.value, PublicationStatus.INBOX_DELIVERED.value]

    last_used = func.coalesce(
        select(func.max(Publication.updated_at)).where(Publication.media_id == MediaAsset.id).scalar_subquery(),
        MediaAsset.created_at,
    )
    in_use = select(Publication.id).where(Publication.media_id == MediaAsset.id,
                                          Publication.status.in_(active)).exists()
    delivered = select(Publication.id).where(Publication.media_id == MediaAsset.id,
                                             Publication.status.in_(done)).exists()

    stale = (
        await db.execute(
            select(MediaAsset).where(
                MediaAsset.status == "ready",
                ~in_use,
                (last_used < now - timedelta(hours=settings.media_retention_hours))
                | (delivered & (last_used < now - timedelta(hours=settings.media_after_finish_hours))),
            )
        )
    ).scalars().all()
    for asset in stale:
        await svc.purge(db, asset)
    await db.commit()

    orphans = await _remove_orphan_files(db, settings)
    return {"media_purged": len(stale), "orphan_files": orphans}


async def _remove_orphan_files(db: AsyncSession, settings: Settings) -> int:
    root = settings.media_dir
    if not root.is_dir():
        return 0
    known = set((await db.execute(select(MediaAsset.storage_name).where(MediaAsset.status == "ready"))).scalars())

    def sweep() -> int:
        removed = 0
        cutoff = time.time() - 3600
        for entry in root.iterdir():
            if not entry.is_file():
                continue
            if entry.name.startswith(".upload-") and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
                removed += 1
            elif entry.name not in known and entry.stat().st_mtime < time.time() - 86400:
                entry.unlink(missing_ok=True)
                removed += 1
        return removed

    return await asyncio.to_thread(sweep)
