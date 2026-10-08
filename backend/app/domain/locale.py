SUPPORTED_LOCALES = ("ru", "kk", "en")


def choose_locale(accept_language: str | None, *, default: str = "ru") -> str:
    for part in (accept_language or "").split(","):
        candidate = part.split(";", 1)[0].strip().lower().split("-", 1)[0]
        if candidate in SUPPORTED_LOCALES:
            return candidate
    return default
