# ADR 0003: PostgreSQL is authoritative

PostgreSQL is the source of truth for users, sessions, connected accounts, media,
publications and audit events. Redis is deliberately disposable and is limited to
rate limits, Celery transport and short-lived coordination.
