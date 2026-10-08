import re

LOG_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def normalize_log_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate if LOG_ID_PATTERN.fullmatch(candidate) else None
