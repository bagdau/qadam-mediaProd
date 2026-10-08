from urllib.parse import urlparse


def validate_upload_url(value: str, *, allowed_hosts: frozenset[str] = frozenset()) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("TikTok upload URL must be an HTTPS origin")
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        raise ValueError("TikTok upload URL host is not allow-listed")
    return value
