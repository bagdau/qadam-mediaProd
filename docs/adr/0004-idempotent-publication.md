# ADR 0004: Idempotent publication requests

Publication creation requires a caller-supplied idempotency key scoped to a user.
The database uniqueness constraint is the final concurrency guard; application
checks exist only to provide a clearer response.
