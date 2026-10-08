from datetime import datetime, timedelta


def lease_deadline(now: datetime, *, seconds: int = 120) -> datetime:
    if seconds < 1:
        raise ValueError("lease duration must be positive")
    return now + timedelta(seconds=seconds)


def lease_expired(now: datetime, deadline: datetime | None) -> bool:
    return deadline is None or deadline <= now
