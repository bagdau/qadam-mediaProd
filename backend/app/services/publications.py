from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.redaction import redact
from app.integrations.tiktok.client import CreatorInfo
from app.integrations.tiktok.errors import TikTokError
from app.models import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    AccountStatus,
    MediaAsset,
    Publication,
    PublicationEvent,
    PublicationMode,
    PublicationStatus,
)
from app.schemas.publication import PublicationCreate
from app.services import audit
from app.services.audit import RequestContext
from app.services.dispatch import Dispatcher
from app.services.media import MediaService
from app.services.tiktok_accounts import TikTokAccountService, to_http_error

REQUIRED_SCOPE = {
    PublicationMode.DIRECT_POST.value: "video.publish",
    PublicationMode.UPLOAD_TO_INBOX.value: "video.upload",
}


def add_event(
    db: AsyncSession,
    pub: Publication,
    type_: str,
    message: str = "",
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        PublicationEvent(
            publication_id=pub.id,
            type=type_,
            from_status=from_status,
            to_status=to_status,
            message=message,
            details=redact(details) if details else None,
        )
    )


def transition(db: AsyncSession, pub: Publication, to: PublicationStatus, message: str = "",
               details: dict[str, Any] | None = None) -> None:
    previous = pub.status
    pub.status = to.value
    if to in TERMINAL_STATUSES:
        pub.finished_at = datetime.now(UTC)
        pub.lease_until = None
    add_event(db, pub, "status_changed", message, from_status=previous, to_status=to.value, details=details)


def validate_against_creator(data: PublicationCreate, creator: CreatorInfo, media: MediaAsset,
                             settings: Settings) -> None:
    """Rules from the TikTok Content Posting API / Content Sharing Guidelines."""
    if data.mode == PublicationMode.DIRECT_POST:
        if data.privacy_level not in creator.privacy_level_options:
            raise ValidationFailed("Выбранный уровень приватности недоступен этому аккаунту TikTok",
                                   code="privacy_not_allowed")
        if not settings.tiktok_client_audited and data.privacy_level != "SELF_ONLY":
            raise ValidationFailed(
                "Приложение ещё не прошло аудит TikTok: публикация доступна только с видимостью «Только я»",
                code="unaudited_private_only",
            )
        if data.brand_content_toggle and data.privacy_level == "SELF_ONLY":
            raise ValidationFailed("Брендированный контент нельзя публиковать с видимостью «Только я»",
                                   code="branded_private")
    if data.allow_comment and creator.comment_disabled:
        raise ValidationFailed("Комментарии отключены в настройках этого аккаунта TikTok", code="comment_disabled")
    if data.allow_duet and creator.duet_disabled:
        raise ValidationFailed("Duet отключён в настройках этого аккаунта TikTok", code="duet_disabled")
    if data.allow_stitch and creator.stitch_disabled:
        raise ValidationFailed("Stitch отключён в настройках этого аккаунта TikTok", code="stitch_disabled")
    maximum = creator.max_video_post_duration_sec
    if maximum and media.duration_seconds and media.duration_seconds > maximum + 0.5:
        raise ValidationFailed(f"Этот аккаунт может публиковать видео не длиннее {maximum} с",
                               code="video_too_long")


class PublicationService:
    def __init__(self, tiktok: TikTokAccountService, media: MediaService, dispatcher: Dispatcher,
                 settings: Settings | None = None) -> None:
        self.tiktok = tiktok
        self.media = media
        self.dispatcher = dispatcher
        self.settings = settings or get_settings()

    async def create(self, db: AsyncSession, user_id: uuid.UUID, data: PublicationCreate, idempotency_key: str,
                     ctx: RequestContext) -> tuple[Publication, bool]:
        """Returns ``(publication, created)``. A repeated Idempotency-Key returns the original row."""
        existing = await self._by_key(db, user_id, idempotency_key)
        if existing:
            return existing, False

        account = await self.tiktok.get_owned(db, user_id, data.account_id)
        if account.status != AccountStatus.ACTIVE.value:
            raise Conflict("TikTok-аккаунт отключён или требует повторного подключения", code="account_inactive")
        needed = REQUIRED_SCOPE[data.mode.value]
        if needed not in (account.scopes or []):
            raise ValidationFailed(f"Для этого режима нужно разрешение TikTok «{needed}». Подключите аккаунт заново.",
                                   code="scope_missing")
        media = await self.media.get_owned(db, user_id, data.media_id)

        if not data.allow_duplicate:
            dup = (
                await db.execute(
                    select(Publication.id, Publication.status).where(
                        Publication.account_id == account.id,
                        Publication.media_id == media.id,
                        Publication.status.in_(
                            [s.value for s in ACTIVE_STATUSES]
                            + [PublicationStatus.PUBLISHED.value, PublicationStatus.NEEDS_REVIEW.value]
                        ),
                    ).limit(1)
                )
            ).first()
            if dup:
                raise Conflict("Это видео уже публиковалось или публикуется в этот аккаунт", code="duplicate_publication",
                               details={"publication_id": str(dup.id), "status": dup.status})

        try:
            creator = await self.tiktok.creator_info(account.id)
        except TikTokError as exc:
            raise to_http_error(exc) from exc
        if not creator.privacy_level_options:
            raise Conflict("Аккаунт TikTok сейчас не может публиковать видео. Повторите позже.", code="creator_cannot_post")
        validate_against_creator(data, creator, media, self.settings)

        pub = Publication(
            user_id=user_id,
            account_id=account.id,
            media_id=media.id,
            idempotency_key=idempotency_key,
            mode=data.mode.value,
            status=PublicationStatus.QUEUED.value,
            title=data.title,
            privacy_level=data.privacy_level,
            disable_comment=not data.allow_comment,
            disable_duet=not data.allow_duet,
            disable_stitch=not data.allow_stitch,
            brand_content_toggle=data.brand_content_toggle,
            brand_organic_toggle=data.brand_organic_toggle,
            is_aigc=data.is_aigc,
            cover_timestamp_ms=data.cover_timestamp_ms,
        )
        db.add(pub)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await self._by_key(db, user_id, idempotency_key)  # lost a race with a twin request
            if existing:
                return existing, False
            raise
        add_event(db, pub, "created", "Публикация поставлена в очередь", to_status=pub.status,
                  details={"mode": pub.mode, "privacy_level": pub.privacy_level})
        await audit.record(db, "publication.created", user_id=user_id, entity_type="publication", entity_id=pub.id,
                           ctx=ctx, details={"mode": pub.mode, "account_id": str(account.id)})
        await db.commit()
        self.dispatcher.publish(pub.id)
        return pub, True

    async def _by_key(self, db: AsyncSession, user_id: uuid.UUID, key: str) -> Publication | None:
        return (
            await db.execute(select(Publication).where(Publication.user_id == user_id,
                                                         Publication.idempotency_key == key))
        ).scalar_one_or_none()

    async def get_owned(self, db: AsyncSession, user_id: uuid.UUID, publication_id: uuid.UUID) -> Publication:
        pub = (
            await db.execute(select(Publication).where(Publication.id == publication_id,
                                                        Publication.user_id == user_id))
        ).scalar_one_or_none()
        if not pub:
            raise NotFound("Публикация не найдена")
        return pub

    async def list_page(self, db: AsyncSession, user_id: uuid.UUID, *, status: str | None, account_id: uuid.UUID | None,
                        limit: int, offset: int) -> tuple[list[Publication], int]:
        conditions = [Publication.user_id == user_id]
        if status:
            conditions.append(Publication.status == status)
        if account_id:
            conditions.append(Publication.account_id == account_id)
        total = (await db.execute(select(func.count()).select_from(Publication).where(*conditions))).scalar_one()
        rows = await db.execute(
            select(Publication).where(*conditions).order_by(Publication.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.scalars()), total

    async def events(self, db: AsyncSession, publication_id: uuid.UUID) -> list[PublicationEvent]:
        rows = await db.execute(
            select(PublicationEvent).where(PublicationEvent.publication_id == publication_id)
            .order_by(PublicationEvent.created_at, PublicationEvent.id)
        )
        return list(rows.scalars())

    async def cancel(self, db: AsyncSession, user_id: uuid.UUID, publication_id: uuid.UUID,
                     ctx: RequestContext) -> Publication:
        pub = await self.get_owned(db, user_id, publication_id)
        now = datetime.now(UTC)
        # Only a publication that no worker has started can be cancelled; the conditional UPDATE is atomic.
        result = await db.execute(
            update(Publication)
            .where(Publication.id == pub.id, Publication.status == PublicationStatus.QUEUED.value)
            .values(status=PublicationStatus.CANCELLED.value, finished_at=now, updated_at=now)
        )
        if result.rowcount == 0:
            await db.rollback()
            raise Conflict("Публикацию уже нельзя отменить: обработка началась или завершена", code="not_cancellable")
        await db.refresh(pub)
        add_event(db, pub, "status_changed", "Отменено пользователем", from_status="QUEUED", to_status="CANCELLED")
        await audit.record(db, "publication.cancelled", user_id=user_id, entity_type="publication", entity_id=pub.id,
                           ctx=ctx)
        await db.commit()
        return pub

    async def retry(self, db: AsyncSession, user_id: uuid.UUID, publication_id: uuid.UUID,
                    confirm_duplicate_risk: bool, ctx: RequestContext) -> Publication:
        pub = await self.get_owned(db, user_id, publication_id)
        if pub.status not in (PublicationStatus.FAILED.value, PublicationStatus.NEEDS_REVIEW.value):
            raise Conflict("Повторить можно только неудавшуюся публикацию", code="not_retryable")
        if pub.status == PublicationStatus.NEEDS_REVIEW.value and not confirm_duplicate_risk:
            raise Conflict(
                "Неизвестно, принял ли TikTok предыдущий запрос. Проверьте профиль и черновики TikTok; "
                "если видео нет, подтвердите повтор.",
                code="duplicate_risk",
            )
        media = (await db.execute(select(MediaAsset).where(MediaAsset.id == pub.media_id))).scalar_one()
        if media.status != "ready":
            raise Conflict("Файл видео уже удалён. Загрузите его заново.", code="media_gone")
        previous = pub.status
        pub.status = PublicationStatus.QUEUED.value
        pub.tiktok_publish_id = None
        pub.upload_url_enc = None
        pub.chunk_size = pub.total_chunks = None
        pub.uploaded_bytes = 0
        pub.fail_reason = pub.fail_message = None
        pub.finished_at = None
        pub.lease_until = None
        pub.next_poll_at = None
        pub.poll_count = 0
        add_event(db, pub, "retry", "Повторная попытка по запросу пользователя", from_status=previous,
                  to_status="QUEUED", details={"confirm_duplicate_risk": confirm_duplicate_risk})
        await audit.record(db, "publication.retried", user_id=user_id, entity_type="publication", entity_id=pub.id,
                           ctx=ctx)
        await db.commit()
        self.dispatcher.publish(pub.id)
        return pub
