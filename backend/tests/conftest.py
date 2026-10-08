from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# --- environment must be prepared before the app modules read settings ----------------------
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://qadam:testpw@127.0.0.1:54329/qadam_test"
)
_MEDIA_DIR = Path(tempfile.mkdtemp(prefix="qadam-media-test-"))

from cryptography.fernet import Fernet  # noqa: E402

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DB_URL,
        "SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
        "ENCRYPTION_KEYS": Fernet.generate_key().decode(),
        "COOKIE_SECURE": "false",
        "PUBLIC_URL": "http://testserver",
        "TIKTOK_CLIENT_KEY": "test-client-key",
        "TIKTOK_CLIENT_SECRET": "test-client-secret-value",
        "TIKTOK_REDIRECT_URI": "https://qadam.test/oauth/tiktok/callback",
        "TIKTOK_SCOPES": "user.info.basic,video.publish,video.upload",
        "MEDIA_DIR": str(_MEDIA_DIR),
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "SECRETS_DIR": str(_MEDIA_DIR / "no-secrets"),
        "MAX_VIDEO_MB": "8",
    }
)

import fakeredis.aioredis  # noqa: E402
import httpx  # noqa: E402
import respx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.crypto import Crypto  # noqa: E402
from app.integrations.tiktok.client import TikTokClient  # noqa: E402
from app.integrations.tiktok.rate_limit import TikTokRateLimiter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import ConnectedAccount, MediaAsset, User  # noqa: E402
from app.services import auth as auth_service  # noqa: E402
from app.services.dispatch import RecordingDispatcher  # noqa: E402
from app.services.media import MediaService  # noqa: E402
from app.services.publications import PublicationService  # noqa: E402
from app.services.publishing import PublishingWorkflow, WorkflowDeps  # noqa: E402
from app.services.tiktok_accounts import TikTokAccountService  # noqa: E402

from tests.fake_tiktok import FakeTikTok, OPEN_ID  # noqa: E402
from tests.helpers import make_mp4  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Correct-Horse-Battery-9"


def run_alembic(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
        cwd=BACKEND_DIR, check=True, capture_output=True, text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    """Fresh schema built *by the Alembic migrations* (so every test exercises them)."""
    import asyncio

    async def reset() -> None:
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset())
    run_alembic(TEST_DB_URL, "upgrade", "head")


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def sessions(_database) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE audit_logs, publication_events, publications, media_assets, oauth_states, "
            "connected_accounts, sessions, users RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def tiktok_mock() -> FakeTikTok:
    with respx.mock(assert_all_called=False) as router:
        yield FakeTikTok(router)


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def media_dir(settings: Settings) -> Path:
    for item in settings.media_dir.glob("*"):
        if item.is_file():
            item.unlink()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    return settings.media_dir


@pytest.fixture
def crypto(settings: Settings) -> Crypto:
    return Crypto(settings.encryption_key_list)


@pytest.fixture
async def tiktok_client(settings: Settings) -> AsyncIterator[TikTokClient]:
    client = TikTokClient(settings)
    yield client
    await client.aclose()


@pytest.fixture
def account_service(tiktok_client, redis, crypto, sessions, settings) -> TikTokAccountService:
    return TikTokAccountService(tiktok_client, TikTokRateLimiter(redis), crypto, sessions, settings)


@pytest.fixture
def workflow(sessions, account_service, dispatcher, settings) -> PublishingWorkflow:
    return PublishingWorkflow(WorkflowDeps.build(sessions, account_service, dispatcher, settings))


@pytest.fixture
def publication_service(account_service, dispatcher, settings, media_dir) -> PublicationService:
    return PublicationService(account_service, MediaService(settings), dispatcher, settings)


@pytest.fixture
async def app(sessions, redis, tiktok_client, dispatcher, settings, media_dir, tiktok_mock):
    application = create_app(settings=settings, redis=redis, sessions=sessions, tiktok_client=tiktok_client,
                             dispatcher=dispatcher)
    async with application.router.lifespan_context(application):
        yield application


class ApiClient(httpx.AsyncClient):
    """Test client that remembers the CSRF token and sends it on state-changing requests."""

    csrf: str | None = None

    async def request(self, method, url, **kwargs):  # type: ignore[override]
        if self.csrf and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", self.csrf)
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)


@pytest.fixture
async def client(app) -> AsyncIterator[ApiClient]:
    async with ApiClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def make_user(sessions, email: str = "owner@example.com", password: str = PASSWORD) -> User:
    async with sessions() as db:
        return await auth_service.create_user(db, email, password, display_name="Owner")


async def login(client: ApiClient, email: str = "owner@example.com", password: str = PASSWORD) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    client.csrf = body["csrf_token"]
    return body


@pytest.fixture
async def user(sessions) -> User:
    return await make_user(sessions)


@pytest.fixture
async def authed(client, user) -> ApiClient:
    await login(client)
    return client


async def make_account(sessions, crypto: Crypto, user_id, *, scopes=None, access="acc-0", refresh="ref-0",
                       expires_in_seconds: int = 86400, status: str = "active") -> ConnectedAccount:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    async with sessions() as db:
        account = ConnectedAccount(
            user_id=user_id, provider="tiktok", provider_account_id=OPEN_ID, username="tester",
            display_name="Test Creator", scopes=scopes or ["user.info.basic", "video.publish", "video.upload"],
            access_token_enc=crypto.encrypt(access), refresh_token_enc=crypto.encrypt(refresh),
            access_expires_at=now + timedelta(seconds=expires_in_seconds),
            refresh_expires_at=now + timedelta(days=300), status=status, connected_at=now,
        )
        db.add(account)
        await db.commit()
        return account


async def make_media(sessions, settings: Settings, user_id, *, size_payload: int = 4096, duration: float = 12.0,
                     content: bytes | None = None, name: str | None = None) -> MediaAsset:
    import hashlib
    import uuid

    data = content if content is not None else make_mp4(duration, size_payload)
    storage = name or f"{uuid.uuid4()}.mp4"
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / storage).write_bytes(data)
    async with sessions() as db:
        asset = MediaAsset(user_id=user_id, original_filename="clip.mp4", storage_name=storage,
                           content_type="video/mp4", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                           duration_seconds=duration)
        db.add(asset)
        await db.commit()
        return asset
