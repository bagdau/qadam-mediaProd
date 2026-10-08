from collections.abc import Iterable


def completion_rate(statuses: Iterable[str]) -> float:
    values = list(statuses)
    if not values:
        return 0.0
    completed = sum(status in {"PUBLISHED", "INBOX_DELIVERED"} for status in values)
    return completed / len(values)
