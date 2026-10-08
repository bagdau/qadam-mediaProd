import re

MAX_CAPTION_UNITS = 2200


def normalize_caption(value: str) -> str:
    """Normalize line endings and trailing whitespace without changing words."""
    lines = (re.sub(r"[ \t]+$", "", line) for line in value.replace("\r\n", "\n").split("\n"))
    return "\n".join(lines).strip()


def validate_caption(value: str) -> str:
    normalized = normalize_caption(value)
    if len(normalized.encode("utf-16-le")) // 2 > MAX_CAPTION_UNITS:
        raise ValueError("caption exceeds 2200 UTF-16 code units")
    return normalized
