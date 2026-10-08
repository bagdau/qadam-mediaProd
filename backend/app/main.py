from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import oauth
from app.api.v1 import accounts, auth, media, misc, publications
from app.core.config import Settings, get_settings
from app.core.crypto import Crypto
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_sessionmaker
from app.integrations.tiktok.client import TikTokClient
from app.integrations.tiktok.rate_limit import TikTokRateLimiter
from app.services import auth as auth_service
from app.services.dispatch import CeleryDispatcher, Dispatcher
from app.services.media import MediaService
from app.services.publications import PublicationService
from app.services.tiktok_accounts import TikTokAccountService

logger = logging.getLogger("app")

API_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def create_app(
    *,
    settings: Settings | None = None,
    redis: Any | None = None,
    sessions: async_sessionmaker[AsyncSession] | None = None,
    tiktok_client: TikTokClient | None = None,
    dispatcher: Dispatcher | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.redis = redis or aioredis.from_url(settings.redis_dsn, decode_responses=True)
        app.state.sessions = sessions or get_sessionmaker()
        client = tiktok_client or TikTokClient(settings)
        crypto = Crypto(settings.encryption_key_list)
        app.state.tiktok_client = client
        app.state.dispatcher = dispatcher or CeleryDispatcher()
        app.state.tiktok_service = TikTokAccountService(
            client, TikTokRateLimiter(app.state.redis), crypto, app.state.sessions, settings
        )
        app.state.media_service = MediaService(settings)
        app.state.publication_service = PublicationService(
            app.state.tiktok_service, app.state.media_service, app.state.dispatcher, settings
        )
        (settings.media_dir / ".tmp").mkdir(parents=True, exist_ok=True)
        async with app.state.sessions() as db:
            await auth_service.ensure_bootstrap_admin(db, settings)
        yield
        if tiktok_client is None:
            await client.aclose()
        if redis is None:
            await app.state.redis.aclose()
        if sessions is None:
            await dispose_engine()

    app = FastAPI(
        title="Qadam Media API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )

    if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
        # 127.0.0.1: the container's own health probe (nginx always forwards the canonical Host)
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*settings.allowed_hosts, "127.0.0.1"])
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
            max_age=600,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        for key, value in API_SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api"):
            response.headers.setdefault("Cache-Control", "no-store")
        logger.info("request", extra={"request_id": request_id, "path": request.url.path,
                                      "status": response.status_code,
                                      "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        body: dict[str, Any] = {"error": {"code": exc.code, "message": exc.message}}
        if exc.details is not None:
            body["error"]["details"] = exc.details
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # Never echo submitted values back (they may contain passwords).
        errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
                  for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_failed", "message": "Проверьте введённые данные",
                                       "details": errors}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": f"http_{exc.status_code}", "message": str(exc.detail)}},
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера"}},
                            status_code=500)

    # ---- health ---------------------------------------------------------
    @app.get("/health/live", include_in_schema=False)
    @app.get("/health", include_in_schema=False)
    async def live():
        return {"status": "ok", "service": "qadam-media"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready(request: Request):
        checks: dict[str, str] = {}
        try:
            async with request.app.state.sessions() as db:
                await db.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception:  # noqa: BLE001
            checks["postgres"] = "error"
        try:
            await request.app.state.redis.ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "error"
        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks},
                            status_code=200 if healthy else 503)

    prefix = "/api/v1"
    for router in (auth.router, accounts.router, media.router, publications.router, misc.router):
        app.include_router(router, prefix=prefix)
    app.include_router(oauth.router)
    return app


def app_factory() -> FastAPI:  # `uvicorn app.main:app_factory --factory`
    return create_app()
