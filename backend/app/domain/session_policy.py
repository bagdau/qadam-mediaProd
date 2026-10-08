from datetime import datetime, timedelta


def session_is_active(
    *, now: datetime, last_seen_at: datetime, expires_at: datetime, revoked_at: datetime | None, idle_ttl: timedelta
) -> bool:
    return revoked_at is None and expires_at > now and last_seen_at + idle_ttl > now
