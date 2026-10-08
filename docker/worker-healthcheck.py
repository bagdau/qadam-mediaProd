"""Exit non-zero when no Celery worker responds to a ping."""

from app.workers.celery_app import celery_app


def main() -> int:
    replies = celery_app.control.inspect(timeout=2.0).ping() or {}
    return 0 if replies else 1


if __name__ == "__main__":
    raise SystemExit(main())
