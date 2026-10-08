from datetime import datetime


def oauth_state_is_usable(*, now: datetime, expires_at: datetime, consumed_at: datetime | None) -> bool:
    return consumed_at is None and expires_at > now


def normalize_scopes(scopes: list[str]) -> tuple[str, ...]:
    return tuple(sorted({scope.strip() for scope in scopes if scope.strip()}))
