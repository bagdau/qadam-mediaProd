from pathlib import Path


def safe_display_filename(value: str, *, fallback: str = "video") -> str:
    name = Path(value.replace("\\", "/")).name.strip().replace("\x00", "")
    if name in {"", ".", ".."}:
        return fallback
    return name[:255]
