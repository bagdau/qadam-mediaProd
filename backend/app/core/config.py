"""Application settings.

Values come from environment variables. Secrets may additionally be provided as
files (Docker/Compose secrets) under ``SECRETS_DIR`` (default ``/run/secrets``):
a file named like the lower-cased field (``tiktok_client_secret``) wins over
nothing but is overridden by an explicit environment variable.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

OFFICIAL_AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
OFFICIAL_API_BASE = "https://open.tiktokapis.com/v2"

_MIN_SECRET_LEN = 32
_PLACEHOLDERS = {"", "change-me", "changeme", "change-me-in-production"}


def _secrets_dir() -> str | None:
    directory = os.environ.get("SECRETS_DIR", "/run/secrets")
    return directory if Path(directory).is_dir() else None


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            return value
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE"),
        env_file_encoding="utf-8",
        secrets_dir=_secrets_dir(),
        extra="ignore",
        case_sensitive=False,
    )

    # --- general -----------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True
    public_url: str = "http://localhost:8080"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    secret_key: SecretStr = SecretStr("")
    encryption_keys: SecretStr = SecretStr("")

    # --- database / redis --------------------------------------------------
    database_url: str | None = None
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "qadam"
    postgres_user: str = "qadam"
    postgres_password: SecretStr = SecretStr("")
    redis_url: str = "redis://redis:6379/0"
    redis_password: SecretStr = SecretStr("")
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # --- sessions / auth ---------------------------------------------------
    cookie_secure: bool = True
    cookie_domain: str | None = None
    session_cookie_name: str = "qm_session"
    csrf_cookie_name: str = "qm_csrf"
    session_ttl_hours: int = 24 * 7
    session_idle_hours: int = 24
    allow_registration: bool = False
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr = SecretStr("")
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # --- TikTok ------------------------------------------------------------
    tiktok_client_key: str = ""
    tiktok_client_secret: SecretStr = SecretStr("")
    tiktok_redirect_uri: str = "http://localhost:8080/oauth/tiktok/callback"
    tiktok_scopes: str = "user.info.basic,video.publish"
    tiktok_authorize_url: str = OFFICIAL_AUTHORIZE_URL
    tiktok_api_base: str = OFFICIAL_API_BASE
    # Un-audited TikTok clients may only post SELF_ONLY content (TikTok docs).
    tiktok_client_audited: bool = False
    oauth_state_ttl_seconds: int = 600
    tiktok_http_timeout: float = 30.0
    tiktok_refresh_leeway_seconds: int = 600

    # --- media -------------------------------------------------------------
    media_dir: Path = Path("/data/media")
    max_video_mb: int = 512
    media_retention_hours: int = 48
    media_after_finish_hours: int = 24

    # --- workers -----------------------------------------------------------
    publish_max_retries: int = 6
    poll_initial_seconds: int = 10
    poll_max_interval_seconds: int = 300
    poll_give_up_hours: int = 6

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def max_video_bytes(self) -> int:
        return self.max_video_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        from urllib.parse import quote

        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql+asyncpg://{quote(self.postgres_user, safe='')}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_dsn(self) -> str:
        """``redis_url`` with the password (Docker secret) injected, unless the URL already has credentials."""
        password = self.redis_password.get_secret_value()
        if not password or "@" in self.redis_url:
            return self.redis_url
        from urllib.parse import quote

        scheme, _, rest = self.redis_url.partition("://")
        return f"{scheme}://:{quote(password, safe='')}@{rest}"

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or _with_db(self.redis_dsn, 1)

    @property
    def result_backend_url(self) -> str:
        return self.celery_result_backend or _with_db(self.redis_dsn, 2)

    @property
    def scope_list(self) -> list[str]:
        return [s.strip() for s in self.tiktok_scopes.split(",") if s.strip()]

    @property
    def tiktok_configured(self) -> bool:
        return bool(self.tiktok_client_key and self.tiktok_client_secret.get_secret_value())

    @property
    def encryption_key_list(self) -> list[str]:
        return [k.strip() for k in self.encryption_keys.get_secret_value().split(",") if k.strip()]

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if not self.is_production:
            return self
        problems: list[str] = []
        secret = self.secret_key.get_secret_value()
        if secret in _PLACEHOLDERS or len(secret) < _MIN_SECRET_LEN:
            problems.append(f"SECRET_KEY must be at least {_MIN_SECRET_LEN} characters")
        if not self.encryption_key_list:
            problems.append("ENCRYPTION_KEYS must contain at least one Fernet key")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if not self.public_url.startswith("https://"):
            problems.append("PUBLIC_URL must use https in production")
        if self.tiktok_authorize_url != OFFICIAL_AUTHORIZE_URL or self.tiktok_api_base != OFFICIAL_API_BASE:
            problems.append("TikTok endpoint overrides are not allowed in production")
        if self.database_url is None and not self.postgres_password.get_secret_value():
            problems.append("POSTGRES_PASSWORD is required")
        if "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must list explicit hosts in production")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must not contain '*'")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self


def _with_db(url: str, db: int) -> str:
    base, _, tail = url.rpartition("/")
    if tail.isdigit():
        return f"{base}/{db}"
    return f"{url.rstrip('/')}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
