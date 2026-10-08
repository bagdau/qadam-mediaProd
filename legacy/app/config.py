from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8100/oauth/tiktok/callback"
    tiktok_scopes: str = "user.info.basic,video.publish"
    lab_access_key: str = "change-me"
    app_secret: str = "change-me-in-production"
    cookie_secure: bool = False
    port: int = 8100

    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8")


settings = Settings()

