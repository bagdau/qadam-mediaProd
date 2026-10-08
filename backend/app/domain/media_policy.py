ALLOWED_VIDEO_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})


def validate_media(*, content_type: str, size_bytes: int, maximum_bytes: int) -> None:
    if content_type.lower() not in ALLOWED_VIDEO_TYPES:
        raise ValueError("unsupported video content type")
    if size_bytes <= 0:
        raise ValueError("video must not be empty")
    if size_bytes > maximum_bytes:
        raise ValueError("video exceeds configured size limit")
