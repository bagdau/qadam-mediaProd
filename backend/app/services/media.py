from __future__ import annotations

import asyncio
import hashlib
import os
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.models import ACTIVE_STATUSES, MediaAsset, Publication
from app.services import audit
from app.services.audit import RequestContext
from app.services.mediainfo import ALLOWED_TYPES, detect_content_type, mp4_duration_seconds

_STORAGE_NAME_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(mp4|mov|webm)$")
_PIECE = 1024 * 1024
MAX_DURATION_SECONDS = 4 * 3600


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media_type"


def sanitize_filename(name: str | None) -> str:
    """Display-only name: no directories, control characters or oversized strings."""
    base = (name or "video").replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*')
    base = base.strip(" .") or "video"
    return base[:200]


def media_path(storage_name: str, settings: Settings | None = None) -> Path:
    """Resolve a stored file name. Rejects anything that is not ``<uuid>.<ext>`` (path traversal guard)."""
    settings = settings or get_settings()
    if not _STORAGE_NAME_RE.match(storage_name):
        raise ValueError("invalid storage name")
    root = settings.media_dir.resolve()
    path = (root / storage_name).resolve()
    if path.parent != root:
        raise ValueError("path escapes media directory")
    return path


class MediaService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def save_upload(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        upload: UploadFile,
        *,
        client_duration: float | None,
        ctx: RequestContext,
    ) -> MediaAsset:
        root = self.settings.media_dir
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        tmp = root / f".upload-{uuid.uuid4().hex}.part"
        limit = self.settings.max_video_bytes
        digest = hashlib.sha256()
        size = 0
        head = b""
        try:
            handle = await asyncio.to_thread(open, tmp, "wb")
            try:
                while True:
                    piece = await upload.read(_PIECE)
                    if not piece:
                        break
                    size += len(piece)
                    if size > limit:
                        raise PayloadTooLarge(f"Файл больше допустимых {self.settings.max_video_mb} МБ")
                    if len(head) < 512:
                        head += piece[: 512 - len(head)]
                    digest.update(piece)
                    await asyncio.to_thread(handle.write, piece)
            finally:
                await asyncio.to_thread(handle.close)
            if size == 0:
                raise ValidationFailed("Файл пустой")
            content_type = detect_content_type(head)
            if not content_type:
                raise UnsupportedMedia("Поддерживаются только MP4, MOV и WebM (проверка по содержимому файла)")

            duration = None
            if content_type in {"video/mp4", "video/quicktime"}:
                duration = await asyncio.to_thread(mp4_duration_seconds, tmp)
            if duration is None and client_duration is not None and 0 < client_duration <= MAX_DURATION_SECONDS:
                duration = float(client_duration)

            storage_name = f"{uuid.uuid4()}{ALLOWED_TYPES[content_type]}"
            final = media_path(storage_name, self.settings)
            await asyncio.to_thread(os.replace, tmp, final)
        except BaseException:
            await asyncio.to_thread(_unlink_quiet, tmp)
            raise

        asset = MediaAsset(
            user_id=user_id,
            original_filename=sanitize_filename(upload.filename),
            storage_name=storage_name,
            content_type=content_type,
            size_bytes=size,
            sha256=digest.hexdigest(),
            duration_seconds=duration,
        )
        db.add(asset)
        try:
            await db.flush()
            await audit.record(db, "media.uploaded", user_id=user_id, entity_type="media", entity_id=asset.id, ctx=ctx,
                               details={"size": size, "content_type": content_type})
            await db.commit()
        except BaseException:
            await db.rollback()
            await asyncio.to_thread(_unlink_quiet, final)
            raise
        return asset

    async def get_owned(self, db: AsyncSession, user_id: uuid.UUID, media_id: uuid.UUID) -> MediaAsset:
        asset = (
            await db.execute(select(MediaAsset).where(MediaAsset.id == media_id, MediaAsset.user_id == user_id))
        ).scalar_one_or_none()
        if not asset or asset.status != "ready":
            raise NotFound("Видео не найдено")
        return asset

    async def delete(self, db: AsyncSession, user_id: uuid.UUID, media_id: uuid.UUID, ctx: RequestContext) -> None:
        asset = await self.get_owned(db, user_id, media_id)
        busy = (
            await db.execute(
                select(Publication.id)
                .where(Publication.media_id == asset.id, Publication.status.in_([s.value for s in ACTIVE_STATUSES]))
                .limit(1)
            )
        ).first()
        if busy:
            raise Conflict("Видео используется в незавершённой публикации", code="media_busy")
        await self.purge(db, asset)
        await audit.record(db, "media.deleted", user_id=user_id, entity_type="media", entity_id=asset.id, ctx=ctx)
        await db.commit()

    async def purge(self, db: AsyncSession, asset: MediaAsset) -> None:
        """Remove the file and mark the row deleted (history rows keep referencing it)."""
        try:
            await asyncio.to_thread(_unlink_quiet, media_path(asset.storage_name, self.settings))
        except ValueError:
            pass
        asset.status = "deleted"
        asset.deleted_at = datetime.now(UTC)

    def path_for(self, asset: MediaAsset) -> Path:
        return media_path(asset.storage_name, self.settings)


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
