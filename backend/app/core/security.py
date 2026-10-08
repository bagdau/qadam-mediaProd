from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Verified against when the user does not exist, to equalise timing.
_DUMMY_HASH = _hasher.hash("qadam-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
        return password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Keyed hash of an opaque bearer value (session token, OAuth state)."""
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def csrf_for_session(session_token: str) -> str:
    """CSRF token bound to the session (signed double-submit)."""
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
