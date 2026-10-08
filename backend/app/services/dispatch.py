"""Task dispatch abstraction so services can enqueue work without importing Celery."""

from __future__ import annotations

import uuid
from typing import Protocol


class Dispatcher(Protocol):
    def publish(self, publication_id: uuid.UUID, countdown: float = 0) -> None: ...

    def poll(self, publication_id: uuid.UUID, countdown: float = 0) -> None: ...


class CeleryDispatcher:
    def publish(self, publication_id: uuid.UUID, countdown: float = 0) -> None:
        from app.workers.celery_app import celery_app

        celery_app.send_task("app.workers.tasks.publish_video", args=[str(publication_id)], countdown=countdown)

    def poll(self, publication_id: uuid.UUID, countdown: float = 0) -> None:
        from app.workers.celery_app import celery_app

        celery_app.send_task("app.workers.tasks.poll_publication", args=[str(publication_id)], countdown=countdown)


class RecordingDispatcher:
    """Test double / dry-run dispatcher."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID, float]] = []

    def publish(self, publication_id: uuid.UUID, countdown: float = 0) -> None:
        self.calls.append(("publish", publication_id, countdown))

    def poll(self, publication_id: uuid.UUID, countdown: float = 0) -> None:
        self.calls.append(("poll", publication_id, countdown))
