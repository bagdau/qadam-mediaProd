"""Background publication workflow (executed by Celery workers).

State machine::

    QUEUED -> INITIATING -> UPLOADING -> PROCESSING -> PUBLISHED | INBOX_DELIVERED | FAILED
       |          |                                        ^
       |          +-- uncertain outcome --------------> NEEDS_REVIEW
       +-> CANCELLED

Duplicate-post protection
-------------------------
* A task only runs the init call from ``QUEUED`` and moves the row to ``INITIATING`` *before*
  calling TikTok (committed, with a lease). ``publish_id`` and the encrypted ``upload_url`` are
  stored right after. A redelivered task therefore never calls init twice: it sees ``UPLOADING``
  (resumes the upload), ``PROCESSING`` (no-op) or an expired ``INITIATING`` lease (the worker died
  while the init outcome was unknown) and parks the row in ``NEEDS_REVIEW`` instead of risking a
  second post.
* A live lease on ``INITIATING``/``UPLOADING`` makes a concurrent duplicate task a no-op.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.crypto import Crypto
from app.core.errors import AppError, NotFound
from app.integrations.tiktok.chunks import ChunkPlan, plan_chunks
from app.integrations.tiktok.client import PostInfo, TikTokClient
from app.integrations.tiktok.errors import (
    FAIL_REASON_MESSAGES,
    TikTokApiError,
    TikTokError,
    TikTokRateLimited,
    TikTokScopeError,
    TikTokTransient,
    UploadOffsetMismatch,
    UploadUrlExpired,
    user_message,
)
from app.integrations.tiktok.rate_limit import STATUS_FETCH, VIDEO_INIT
from app.models import (
    TERMINAL_STATUSES,
    AccountStatus,
    ConnectedAccount,
    MediaAsset,
    Publication,
    PublicationMode,
    PublicationStatus,
)
from app.services.dispatch import Dispatcher
from app.services.media import media_path
from app.services.publications import REQUIRED_SCOPE, add_event, transition, validate_against_creator
from app.services.tiktok_accounts import ReauthRequired, TikTokAccountService

logger = logging.getLogger(__name__)


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None

INIT_LEASE = timedelta(minutes=3)
UPLOAD_LEASE = timedelta(minutes=15)
CHUNK_ATTEMPTS = 3


class RetryLater(Exception):
    """The task should be retried by the queue after ``countdown`` seconds."""

    def __init__(self, countdown: float, reason: str) -> None:
        super().__init__(reason)
        self.countdown = countdown
        self.reason = reason


def backoff(attempt: int, base: float = 15.0, cap: float = 900.0) -> float:
    """Exponential backoff with jitter: 15s, 30s, 60s ... capped at 15 min."""
    delay = min(cap, base * (2 ** max(0, attempt)))
    return delay * random.uniform(0.8, 1.2)


@dataclass
class WorkflowDeps:
    sessions: async_sessionmaker[AsyncSession]
    tiktok: TikTokAccountService
    client: TikTokClient
    crypto: Crypto
    dispatcher: Dispatcher
    settings: Settings

    @classmethod
    def build(cls, sessions, tiktok, dispatcher, settings: Settings | None = None) -> WorkflowDeps:
        return cls(sessions, tiktok, tiktok.client, tiktok.crypto, dispatcher, settings or get_settings())


class PublishingWorkflow:
    def __init__(self, deps: WorkflowDeps) -> None:
        self.d = deps

    # ===================================================================== publish
    async def run_publish(self, publication_id: uuid.UUID) -> str:
        """One idempotent execution step. Raises ``RetryLater`` for transient problems."""
        async with self.d.sessions() as db:
            pub = await self._lock(db, publication_id)
            if pub is None:
                return "missing"
            status = pub.status
            now = datetime.now(UTC)
            if status in {s.value for s in TERMINAL_STATUSES} or status == PublicationStatus.PROCESSING.value:
                await db.rollback()
                return "noop"
            leased = pub.lease_until is not None and pub.lease_until > now
            if leased and status in (PublicationStatus.INITIATING.value, PublicationStatus.UPLOADING.value):
                await db.rollback()
                return "busy"
            if status == PublicationStatus.INITIATING.value:  # lease expired: init outcome unknown
                transition(db, pub, PublicationStatus.NEEDS_REVIEW,
                           "Не удалось подтвердить, принял ли TikTok запрос на публикацию. "
                           "Проверьте профиль и черновики TikTok перед повтором.")
                pub.fail_reason = "init_uncertain"
                pub.fail_message = "Результат запроса к TikTok неизвестен (процесс был прерван)."
                await db.commit()
                return "needs_review"
            if status == PublicationStatus.UPLOADING.value:
                pub.lease_until = now + UPLOAD_LEASE
                await db.commit()
                return await self._upload(db, publication_id)

            # ---- QUEUED ----
            return await self._start(db, pub)

    async def _start(self, db: AsyncSession, pub: Publication) -> str:
        account = await db.get(ConnectedAccount, pub.account_id)
        media = await db.get(MediaAsset, pub.media_id)
        pub.attempts += 1
        pub.started_at = pub.started_at or datetime.now(UTC)

        problem = self._precondition_problem(pub, account, media)
        if problem:
            code, message = problem
            return await self._fail(db, pub, code, message)

        assert account is not None and media is not None
        plan = plan_chunks(media.size_bytes)
        try:
            if pub.mode == PublicationMode.DIRECT_POST.value:
                creator = await self.d.tiktok.creator_info(account.id)
                from app.schemas.publication import PublicationCreate  # local: avoid import cycle at module load

                validate_against_creator(
                    PublicationCreate.model_construct(
                        mode=PublicationMode.DIRECT_POST, privacy_level=pub.privacy_level,
                        allow_comment=not pub.disable_comment, allow_duet=not pub.disable_duet,
                        allow_stitch=not pub.disable_stitch, brand_content_toggle=pub.brand_content_toggle,
                    ),
                    creator, media, self.d.settings,
                )
        except ReauthRequired as exc:
            return await self._fail(db, pub, "reauth_required", exc.message)
        except AppError as exc:  # validation of the stored request against current creator limits
            return await self._fail(db, pub, exc.code, exc.message)
        except TikTokRateLimited as exc:
            await self._retry_later(db, pub, exc.retry_after, "rate_limited")
        except TikTokTransient as exc:
            await self._retry_later(db, pub, backoff(pub.attempts), str(exc))
        except TikTokError as exc:
            return await self._fail(db, pub, exc.code or "creator_info_failed", user_message(exc.code, exc.message))

        # --- claim the right to call init (durable before the network call) ---
        transition(db, pub, PublicationStatus.INITIATING, "Запрос на публикацию отправляется в TikTok")
        pub.lease_until = datetime.now(UTC) + INIT_LEASE
        await db.commit()

        try:
            post = PostInfo(
                title=pub.title, privacy_level=pub.privacy_level, disable_comment=pub.disable_comment,
                disable_duet=pub.disable_duet, disable_stitch=pub.disable_stitch,
                cover_timestamp_ms=pub.cover_timestamp_ms, brand_content_toggle=pub.brand_content_toggle,
                brand_organic_toggle=pub.brand_organic_toggle, is_aigc=pub.is_aigc,
            )
            if pub.mode == PublicationMode.DIRECT_POST.value:
                init = await self.d.tiktok.call(account.id, VIDEO_INIT,
                                                lambda tok: self.d.client.init_direct_post(tok, post, plan))
            else:
                init = await self.d.tiktok.call(account.id, VIDEO_INIT,
                                                lambda tok: self.d.client.init_inbox_upload(tok, plan))
        except TikTokRateLimited as exc:
            await self._revert_to_queued(db, pub, "Лимит запросов TikTok, повтор позже")
            raise RetryLater(exc.retry_after, "rate_limited") from exc
        except TikTokTransient as exc:
            if exc.maybe_sent:
                return await self._needs_review(db, pub, "init_uncertain", str(exc))
            await self._revert_to_queued(db, pub, "TikTok временно недоступен, повтор позже")
            raise RetryLater(backoff(pub.attempts), str(exc)) from exc
        except ReauthRequired as exc:
            return await self._fail(db, pub, "reauth_required", exc.message)
        except TikTokError as exc:
            return await self._fail(db, pub, exc.code or "init_failed", user_message(exc.code, exc.message),
                                    details={"log_id": exc.log_id, "http_status": exc.http_status})

        # --- persist the identifiers immediately ---
        pub = await self._lock(db, pub.id) or pub
        pub.tiktok_publish_id = init.publish_id
        pub.upload_url_enc = self.d.crypto.encrypt(init.upload_url)
        pub.chunk_size, pub.total_chunks, pub.uploaded_bytes = plan.chunk_size, plan.total_chunks, 0
        transition(db, pub, PublicationStatus.UPLOADING, "Видео загружается в TikTok",
                   {"publish_id": init.publish_id, "chunks": plan.total_chunks})
        pub.lease_until = datetime.now(UTC) + UPLOAD_LEASE
        await db.commit()
        return await self._upload(db, pub.id)

    # ===================================================================== upload
    async def _upload(self, db: AsyncSession, publication_id: uuid.UUID) -> str:
        pub = await db.get(Publication, publication_id, populate_existing=True)
        assert pub is not None and pub.upload_url_enc and pub.chunk_size and pub.total_chunks
        media = await db.get(MediaAsset, pub.media_id)
        assert media is not None
        path = media_path(media.storage_name, self.d.settings)
        if await asyncio.to_thread(_file_size, path) != media.size_bytes:
            return await self._fail(db, pub, "media_missing", "Файл видео недоступен на сервере.")
        plan = ChunkPlan(media.size_bytes, pub.chunk_size, pub.total_chunks)
        upload_url = self.d.crypto.decrypt(pub.upload_url_enc)

        offset = (pub.uploaded_bytes // plan.chunk_size) * plan.chunk_size  # resume on a chunk boundary
        while True:
            rng = plan.range_at(offset)
            if rng is None:
                break
            first, last = rng
            try:
                code = await self._put_chunk_with_retries(upload_url, path, first, last, media)
            except UploadOffsetMismatch as exc:
                known = exc.uploaded_bytes if exc.uploaded_bytes is not None else first
                new_offset = (known // plan.chunk_size) * plan.chunk_size
                if new_offset == offset:
                    return await self._fail(db, pub, "upload_offset_mismatch", "TikTok отклонил порядок загрузки.")
                offset = new_offset
                continue
            except UploadUrlExpired:
                return await self._fail(db, pub, "upload_url_expired",
                                        "Ссылка загрузки TikTok истекла. Повторите публикацию.")
            except TikTokRateLimited as exc:
                await self._retry_later(db, pub, exc.retry_after, "upload_rate_limited", keep_status=True)
            except TikTokTransient as exc:
                await self._retry_later(db, pub, backoff(pub.attempts), str(exc), keep_status=True)
            except TikTokApiError as exc:
                return await self._fail(db, pub, exc.code or "upload_failed", exc.message)
            pub.uploaded_bytes = last + 1
            pub.lease_until = datetime.now(UTC) + UPLOAD_LEASE
            await db.commit()
            offset = last + 1
            if code == 201 or offset >= plan.video_size:
                break

        interval = self.d.settings.poll_initial_seconds
        pub.next_poll_at = datetime.now(UTC) + timedelta(seconds=interval)
        pub.lease_until = None
        transition(db, pub, PublicationStatus.PROCESSING, "TikTok обрабатывает видео")
        await db.commit()
        self.d.dispatcher.poll(pub.id, countdown=interval)
        return "uploaded"

    async def _put_chunk_with_retries(self, url: str, path: Path, first: int, last: int, media: MediaAsset) -> int:
        last_error: TikTokTransient | None = None
        for attempt in range(CHUNK_ATTEMPTS):
            try:
                return await self.d.client.upload_chunk(url, path, first, last, media.size_bytes, media.content_type)
            except TikTokRateLimited:
                raise
            except TikTokTransient as exc:  # 5xx / network: resubmit the same chunk
                last_error = exc
                await asyncio.sleep(min(2 ** attempt, 8) * (0 if self.d.settings.environment == "test" else 1))
        assert last_error is not None
        raise last_error

    # ======================================================================= poll
    async def poll_status(self, publication_id: uuid.UUID) -> str:
        async with self.d.sessions() as db:
            pub = await self._lock(db, publication_id)
            if pub is None:
                return "missing"
            if pub.status != PublicationStatus.PROCESSING.value or not pub.tiktok_publish_id:
                await db.rollback()
                return "noop"
            publish_id = pub.tiktok_publish_id
            started = pub.started_at or pub.created_at
            await db.commit()  # do not hold the row lock across the network call

            try:
                result = await self.d.tiktok.call(
                    pub.account_id, STATUS_FETCH, lambda tok: self.d.client.fetch_status(tok, publish_id)
                )
            except TikTokRateLimited as exc:
                raise RetryLater(exc.retry_after, "rate_limited") from exc
            except TikTokTransient as exc:
                raise RetryLater(backoff(0, base=30), str(exc)) from exc
            except (ReauthRequired, TikTokScopeError):
                pub = await self._lock(db, publication_id)
                return await self._needs_review(
                    db, pub, "auth_lost", "Не удалось проверить статус: доступ к TikTok недействителен.")
            except TikTokError as exc:
                pub = await self._lock(db, publication_id)
                return await self._fail(db, pub, exc.code or "status_failed", user_message(exc.code, exc.message))

            pub = await self._lock(db, publication_id)
            assert pub is not None
            if pub.status != PublicationStatus.PROCESSING.value:
                await db.rollback()
                return "noop"
            pub.poll_count += 1
            add_event(db, pub, "tiktok_status", result.status, details={
                "status": result.status, "fail_reason": result.fail_reason, "uploaded_bytes": result.uploaded_bytes})

            if result.status == "PUBLISH_COMPLETE":
                pub.tiktok_post_ids = result.post_ids or None
                transition(db, pub, PublicationStatus.PUBLISHED, "Видео опубликовано")
                await db.commit()
                return "published"
            if result.status == "SEND_TO_USER_INBOX" and pub.mode == PublicationMode.UPLOAD_TO_INBOX.value:
                transition(db, pub, PublicationStatus.INBOX_DELIVERED,
                           "Видео доставлено в черновики TikTok. Завершите публикацию в приложении.")
                await db.commit()
                return "inbox"
            if result.status == "FAILED":
                reason = result.fail_reason or "unknown"
                return await self._fail(db, pub, reason, FAIL_REASON_MESSAGES.get(reason, "TikTok не смог обработать видео."))

            give_up = started + timedelta(hours=self.d.settings.poll_give_up_hours)
            if datetime.now(UTC) > give_up:
                return await self._needs_review(db, pub, "processing_timeout",
                                                "TikTok слишком долго обрабатывает видео. Проверьте статус позже.")
            interval = min(self.d.settings.poll_initial_seconds * (2 ** min(pub.poll_count, 10)),
                           self.d.settings.poll_max_interval_seconds)
            pub.next_poll_at = datetime.now(UTC) + timedelta(seconds=interval)
            await db.commit()
            self.d.dispatcher.poll(pub.id, countdown=interval)
            return "processing"

    # ==================================================================== sweeper
    async def sweep(self) -> dict[str, int]:
        """Re-dispatch work that got lost (broker restart, crashed worker). Safe to run often."""
        now = datetime.now(UTC)
        counts = {"publish": 0, "poll": 0}
        async with self.d.sessions() as db:
            queued = (await db.execute(
                select(Publication.id).where(Publication.status == PublicationStatus.QUEUED.value,
                                             Publication.updated_at < now - timedelta(seconds=90)))).scalars().all()
            stale = (await db.execute(
                select(Publication.id).where(
                    Publication.status.in_([PublicationStatus.INITIATING.value, PublicationStatus.UPLOADING.value]),
                    Publication.lease_until < now))).scalars().all()
            polling = (await db.execute(
                select(Publication.id).where(Publication.status == PublicationStatus.PROCESSING.value,
                                             Publication.next_poll_at < now - timedelta(seconds=60)))).scalars().all()
        for pid in [*queued, *stale]:
            self.d.dispatcher.publish(pid)
            counts["publish"] += 1
        for pid in polling:
            self.d.dispatcher.poll(pid)
            counts["poll"] += 1
        return counts

    async def fail_exhausted(self, publication_id: uuid.UUID, reason: str) -> None:
        """Called by the queue after the last retry."""
        async with self.d.sessions() as db:
            pub = await self._lock(db, publication_id)
            if pub is None or pub.status in {s.value for s in TERMINAL_STATUSES}:
                return
            if pub.status == PublicationStatus.PROCESSING.value:
                await self._needs_review(db, pub, "poll_retries_exhausted",
                                         "Не удалось получить статус от TikTok после нескольких попыток.")
            else:
                await self._fail(db, pub, "retries_exhausted",
                                 "Не удалось завершить публикацию после нескольких попыток. " + reason[:200])

    # ===================================================================== helpers
    async def _lock(self, db: AsyncSession, publication_id: uuid.UUID) -> Publication | None:
        return (
            await db.execute(
                select(Publication).where(Publication.id == publication_id)
                .with_for_update().execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    def _precondition_problem(self, pub: Publication, account: ConnectedAccount | None,
                              media: MediaAsset | None) -> tuple[str, str] | None:
        if account is None or account.status != AccountStatus.ACTIVE.value:
            return "account_inactive", "TikTok-аккаунт отключён или требует повторного подключения."
        if REQUIRED_SCOPE[pub.mode] not in (account.scopes or []):
            return "scope_missing", f"Не выдано разрешение TikTok «{REQUIRED_SCOPE[pub.mode]}»."
        if media is None or media.status != "ready":
            return "media_missing", "Файл видео удалён. Загрузите его заново."
        return None

    async def _fail(self, db: AsyncSession, pub: Publication, reason: str, message: str,
                    details: dict | None = None) -> str:
        pub.fail_reason, pub.fail_message = reason[:64], message
        transition(db, pub, PublicationStatus.FAILED, message, {"reason": reason, **(details or {})})
        await db.commit()
        return "failed"

    async def _needs_review(self, db: AsyncSession, pub: Publication, reason: str, message: str) -> str:
        pub.fail_reason, pub.fail_message = reason[:64], message
        transition(db, pub, PublicationStatus.NEEDS_REVIEW, message, {"reason": reason})
        await db.commit()
        return "needs_review"

    async def _revert_to_queued(self, db: AsyncSession, pub: Publication, message: str) -> None:
        pub = await self._lock(db, pub.id) or pub
        pub.lease_until = None
        transition(db, pub, PublicationStatus.QUEUED, message)
        await db.commit()

    async def _retry_later(self, db: AsyncSession, pub: Publication, countdown: float, reason: str,
                           *, keep_status: bool = False) -> None:
        add_event(db, pub, "retry_scheduled", reason, details={"countdown": round(countdown, 1)})
        pub.lease_until = None
        await db.commit()
        raise RetryLater(countdown, reason)


__all__ = ["PublishingWorkflow", "RetryLater", "WorkflowDeps", "backoff", "NotFound"]
