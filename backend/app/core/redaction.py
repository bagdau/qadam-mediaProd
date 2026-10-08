"""Redaction of secrets in log records and stored event details."""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "client_key_secret",
    "password",
    "new_password",
    "current_password",
    "authorization",
    "cookie",
    "set-cookie",
    "code_verifier",
    "upload_url",
    "token",
    "secret",
    "secret_key",
    "encryption_keys",
    "state",
    "csrf",
    "x-csrf-token",
}

_KEY_ALT = "|".join(sorted((re.escape(k) for k in _SENSITIVE_KEYS), key=len, reverse=True))
# "key": "value", key=value, 'key': 'value'
_PAIR_RE = re.compile(
    rf"""(?P<k>["']?\b(?:{_KEY_ALT})["']?\s*[:=]\s*)(?P<v>"[^"]*"|'[^']*'|[^\s,;&}}\])]+)""",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_QUERY_ALT = "|".join(sorted((re.escape(k) for k in _SENSITIVE_KEYS | {"code"}), key=len, reverse=True))
_URL_QUERY_RE = re.compile(
    rf"([?&](?:{_QUERY_ALT})=)[^&\s]+",
    re.IGNORECASE,
)
_TT_UPLOAD_RE = re.compile(r"https://[\w.-]*tiktok[\w.-]*/[^\s\"']*upload[^\s\"']*", re.IGNORECASE)


def redact_text(text: str) -> str:
    text = _BEARER_RE.sub(r"\1" + REDACTED, text)
    text = _URL_QUERY_RE.sub(r"\1" + REDACTED, text)
    text = _TT_UPLOAD_RE.sub(REDACTED, text)

    def _pair(match: re.Match[str]) -> str:
        value = match.group("v")
        quote = value[0] if value[:1] in {'"', "'"} else ""
        return f"{match.group('k')}{quote}{REDACTED}{quote}"

    return _PAIR_RE.sub(_pair, text)


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a deep copy of ``value`` with sensitive values replaced."""
    if _depth > 8:
        return REDACTED
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                out[str(key)] = REDACTED
            else:
                out[str(key)] = redact(item, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [redact(item, _depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            return True
        record.msg = redact_text(message)
        record.args = None
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True
