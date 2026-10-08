from datetime import datetime, time


def in_maintenance_window(now: datetime, *, start: time, end: time) -> bool:
    current = now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= current < end
    return current >= start or current < end
