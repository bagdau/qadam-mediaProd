import base64


def encode_cursor(value: int) -> str:
    if value < 0:
        raise ValueError("cursor must be non-negative")
    return base64.urlsafe_b64encode(str(value).encode()).decode().rstrip("=")


def decode_cursor(value: str) -> int:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        result = int(decoded)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid cursor") from exc
    if result < 0:
        raise ValueError("invalid cursor")
    return result
