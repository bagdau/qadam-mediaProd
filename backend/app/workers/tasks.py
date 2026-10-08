"""Celery tasks. Thin wrappers: all logic lives in ``app.services`` and is unit-tested directly."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.crypto import Crypto
from app.db.session import worker_sessionmaker
from app.integrations.tiktok.client import TikTokClient
from app.integrations.tiktok.rate_limit import TikTokRateLimiter
from app.services import maintenance
from app.services.dispatch import CeleryDispatcher
from app.services.publishing import PublishingWorkflow, RetryLater, WorkflowDeps, backoff
from app.services.tiktok_accounts import TikTokAccountService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
T = TypeVar("T")

POLL_MAX_RETRIES = 30


@asynccontextmanager
async def runtime():
    """Per-task dependencies. Each task runs in a fresh event loop, so nothing loop-bound is shared."""
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_dsn, decode_responses=True)
    client = TikTokClient(settings)
    try:
        async with worker_sessionmaker() as sessions:
            service = TikTokAccountService(client, TikTokRateLimiter(redis), Crypto(settings.encryption_key_list),
                                           sessions, settings)
            deps = WorkflowDeps.build(sessions, service, CeleryDispatcher(), settings)
            yield deps, service
    finally:
        await client.aclose()
        await redis.aclose()


def run(coro_factory: Callable[[WorkflowDeps, TikTokAccountService], Awaitable[T]]) -> T:  # noqa: UP047
    async def main() -> T:
        async with runtime() as (deps, service):
            return await coro_factory(deps, service)

    return asyncio.run(main())


def _handle(task: Any, publication_id: str, step: Callable[[PublishingWorkflow, uuid.UUID], Awaitable[str]],
            max_retries: int) -> str:
    pid = uuid.UUID(publication_id)
    try:
        return run(lambda deps, _svc: step(PublishingWorkflow(deps), pid))
    except RetryLater as retry:
        countdown, reason = retry.countdown, retry.reason
    except Exception as exc:  # noqa: BLE001 - unexpected: retry with backoff, never lose the publication
        logger.exception("unexpected error in %s for %s", task.name, publication_id)
        countdown, reason = backoff(task.request.retries), f"{type(exc).__name__}"

    if task.request.retries >= max_retries:
        run(lambda deps, _svc: PublishingWorkflow(deps).fail_exhausted(pid, reason))
        return "exhausted"
    raise task.retry(countdown=countdown, max_retries=max_retries + 1)


@celery_app.task(name="app.workers.tasks.publish_video", bind=True, acks_late=True)
def publish_video(self, publication_id: str) -> str:
    max_retries = get_settings().publish_max_retries
    return _handle(self, publication_id, lambda wf, pid: wf.run_publish(pid), max_retries)


@celery_app.task(name="app.workers.tasks.poll_publication", bind=True, acks_late=True)
def poll_publication(self, publication_id: str) -> str:
    return _handle(self, publication_id, lambda wf, pid: wf.poll_status(pid), POLL_MAX_RETRIES)


@celery_app.task(name="app.workers.tasks.sweep_publications")
def sweep_publications() -> dict[str, int]:
    return run(lambda deps, _svc: PublishingWorkflow(deps).sweep())


@celery_app.task(name="app.workers.tasks.refresh_tokens")
def refresh_tokens() -> dict[str, int]:
    return run(lambda _deps, service: service.refresh_expiring())


@celery_app.task(name="app.workers.tasks.cleanup_media")
def cleanup_media() -> dict[str, int]:
    async def work(deps: WorkflowDeps, _svc: TikTokAccountService) -> dict[str, int]:
        async with deps.sessions() as db:
            return await maintenance.cleanup_media(db, deps.settings)

    return run(work)


@celery_app.task(name="app.workers.tasks.cleanup_auth")
def cleanup_auth() -> dict[str, int]:
    async def work(deps: WorkflowDeps, _svc: TikTokAccountService) -> dict[str, int]:
        async with deps.sessions() as db:
            return await maintenance.cleanup_auth_rows(db)

    return run(work)
