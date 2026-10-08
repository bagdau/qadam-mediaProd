"""Symmetric encryption for secrets at rest (TikTok tokens, upload URLs).

``ENCRYPTION_KEYS`` is a comma separated list of Fernet keys. The first key
encrypts; all keys can decrypt, which allows zero-downtime key rotation
(prepend a new key, run ``python -m app.cli rotate-encryption``, drop the old).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import Settings, get_settings


class DecryptionError(Exception):
    pass


def generate_key() -> str:
    return Fernet.generate_key().decode()


class Crypto:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise RuntimeError("ENCRYPTION_KEYS is not configured")
        self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:  # never include the token in the message
            raise DecryptionError("cannot decrypt value with configured keys") from exc

    def rotate(self, token: str) -> str:
        """Re-encrypt ``token`` with the primary key."""
        try:
            return self._fernet.rotate(token.encode()).decode()
        except InvalidToken as exc:
            raise DecryptionError("cannot decrypt value with configured keys") from exc


def get_crypto(settings: Settings | None = None) -> Crypto:
    settings = settings or get_settings()
    return Crypto(settings.encryption_key_list)
