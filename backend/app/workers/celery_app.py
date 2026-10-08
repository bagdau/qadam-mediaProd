from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery_app = Celery(
    "qadam",
    broker=settings.broker_url,
    backend=settings.result_backend_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    # Reliability: a task is acknowledged only after it finished, so a crashed worker's
    # task is redelivered. The workflow is idempotent (see app.services.publishing).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    broker_connection_retry_on_startup=True,
    # countdown/ETA tasks (status polling) are held by the worker until due
    broker_transport_options={"visibility_timeout": 4 * 3600},
    worker_hijack_root_logger=False,
    beat_schedule={
        "sweep-publications": {"task": "app.workers.tasks.sweep_publications", "schedule": 60.0},
        "refresh-tokens": {"task": "app.workers.tasks.refresh_tokens", "schedule": 15 * 60.0},
        "cleanup-media": {"task": "app.workers.tasks.cleanup_media", "schedule": crontab(minute=17)},
        "cleanup-auth": {"task": "app.workers.tasks.cleanup_auth", "schedule": crontab(minute=45, hour="*/6")},
    },
)
