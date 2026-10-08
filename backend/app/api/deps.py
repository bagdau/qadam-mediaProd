from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import Forbidden, TooManyRequests, Unauthorized
from app.core.security import constant_time_equals, csrf_for_session
from app.models import Session, User
from app.services import auth as auth_service
from app.services.audit import RequestContext
from app.services.media import MediaService
from app.services.publications import PublicationService
from app.services.tiktok_accounts import TikTokAccountService

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def settings_dep() -> Settings:
    return get_settings()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


def request_ctx(request: Request) -> RequestContext:
    return RequestContext.from_request(request)


def tiktok_service(request: Request) -> TikTokAccountService:
    return request.app.state.tiktok_service


def media_service(request: Request) -> MediaService:
    return request.app.state.media_service


def publication_service(request: Request) -> PublicationService:
    return request.app.state.publication_service


@dataclass
class AuthContext:
    user: User
    session: Session
    token: str


async def optional_auth(request: Request, db: AsyncSession = Depends(get_db),
                        settings: Settings = Depends(settings_dep)) -> AuthContext | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    resolved = await auth_service.resolve_session(db, token)
    if not resolved:
        return None
    user, session = resolved
    return AuthContext(user=user, session=session, token=token)


async def require_auth(auth: AuthContext | None = Depends(optional_auth)) -> AuthContext:
    if auth is None:
        raise Unauthorized()
    return auth


def _allowed_origins(settings: Settings) -> set[str]:
    origins = {settings.public_url.rstrip("/")}
    origins.update(o.rstrip("/") for o in settings.cors_origins)
    return origins


def check_origin(request: Request, settings: Settings) -> None:
    """Reject cross-site browser requests whose Origin/Referer is not ours."""
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if referer:
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin is not None and origin.rstrip("/") not in _allowed_origins(settings):
        raise Forbidden("Недопустимый источник запроса", code="bad_origin")


async def csrf_protect(request: Request, auth: AuthContext = Depends(require_auth),
                       settings: Settings = Depends(settings_dep)) -> None:
    """Signed double-submit CSRF protection for state-changing authenticated requests."""
    if request.method not in UNSAFE_METHODS:
        return
    check_origin(request, settings)
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    expected = csrf_for_session(auth.token)
    if not header or not cookie or not constant_time_equals(header, cookie) or not constant_time_equals(header, expected):
        raise Forbidden("Недействительный CSRF-токен", code="csrf_failed")


async def check_origin_dep(request: Request, settings: Settings = Depends(settings_dep)) -> None:
    if request.method in UNSAFE_METHODS:
        check_origin(request, settings)


async def _hit(request: Request, name: str, ident: str, limit: int, window: int) -> None:
    redis = request.app.state.redis
    window_id = int(time.time() // window)
    key = f"rl:{name}:{ident}:{window_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window + 5)
    if count > limit:
        raise TooManyRequests(retry_after=window - int(time.time() % window) + 1)


def rate_limit(name: str, limit: int, window: int) -> Callable:
    """Fixed-window limiter keyed by client IP (for unauthenticated endpoints)."""

    async def dependency(request: Request) -> None:
        await _hit(request, name, request.client.host if request.client else "unknown", limit, window)

    return dependency


def user_rate_limit(name: str, limit: int, window: int) -> Callable:
    """Fixed-window limiter keyed by the signed-in user."""

    async def dependency(request: Request, auth: AuthContext = Depends(require_auth)) -> None:
        await _hit(request, name, f"u:{auth.user.id}", limit, window)

    return dependency
