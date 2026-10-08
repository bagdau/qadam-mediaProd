# ADR 0007: Pure domain rules

Validation and state-transition rules that do not require I/O live in
`app.domain`. They remain independent of FastAPI, SQLAlchemy and Celery so the
same decisions can be reused and unit-tested in every process role.
