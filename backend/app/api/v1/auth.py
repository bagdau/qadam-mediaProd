from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthContext,
    check_origin_dep,
    csrf_protect,
    get_db,
    rate_limit,
    request_ctx,
    require_auth,
    settings_dep,
)
from app.core.config import Settings
from app.core.errors import Forbidden, NotFound
from app.core.security import csrf_for_session
from app.models import UserRole
from app.schemas.core import (
    AuthResponse,
    LoginRequest,
    PasswordChange,
    RegisterRequest,
    SessionOut,
    UserOut,
)
from app.services import audit
from app.services import auth as auth_service
from app.services.audit import RequestContext

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, settings: Settings, token: str) -> str:
    max_age = settings.session_ttl_hours * 3600
    csrf = csrf_for_session(token)
    common = dict(max_age=max_age, secure=settings.cookie_secure, samesite="lax", path="/",
                  domain=settings.cookie_domain)
    response.set_cookie(settings.session_cookie_name, token, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie_name, csrf, httponly=False, **common)
    return csrf


def _clear_cookies(response: Response, settings: Settings) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/", domain=settings.cookie_domain,
                               secure=settings.cookie_secure, samesite="lax")


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(check_origin_dep), Depends(rate_limit("login", 20, 60))],
)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db),
                ctx: RequestContext = Depends(request_ctx), settings: Settings = Depends(settings_dep)):
    user = await auth_service.authenticate(db, payload.email, payload.password, ctx)
    _session, token = await auth_service.create_session(db, user, ctx)
    csrf = _set_cookies(response, settings, token)
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    dependencies=[Depends(check_origin_dep), Depends(rate_limit("register", 5, 3600))],
)
async def register(payload: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db),
                   ctx: RequestContext = Depends(request_ctx), settings: Settings = Depends(settings_dep)):
    if not settings.allow_registration:
        raise Forbidden("Регистрация отключена администратором", code="registration_disabled")
    user = await auth_service.create_user(db, payload.email, payload.password, display_name=payload.display_name,
                                          role=UserRole.MEMBER, ctx=ctx)
    _session, token = await auth_service.create_session(db, user, ctx)
    csrf = _set_cookies(response, settings, token)
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=csrf)


@router.get("/me", response_model=AuthResponse)
async def me(response: Response, auth: AuthContext = Depends(require_auth), settings: Settings = Depends(settings_dep)):
    response.headers["Cache-Control"] = "no-store"
    csrf = _set_cookies(response, settings, auth.token) if auth.token else ""
    return AuthResponse(user=UserOut.model_validate(auth.user), csrf_token=csrf)


@router.post("/logout", status_code=204, dependencies=[Depends(csrf_protect)])
async def logout(response: Response, auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db),
                 ctx: RequestContext = Depends(request_ctx), settings: Settings = Depends(settings_dep)):
    await auth_service.revoke_session(db, auth.session.id, auth.user.id)
    await audit.record(db, "auth.logout", user_id=auth.user.id, ctx=ctx)
    await db.commit()
    _clear_cookies(response, settings)
    response.status_code = 204
    return response


@router.post("/password", status_code=204, dependencies=[Depends(csrf_protect), Depends(rate_limit("password", 10, 600))])
async def change_password(payload: PasswordChange, auth: AuthContext = Depends(require_auth),
                          db: AsyncSession = Depends(get_db), ctx: RequestContext = Depends(request_ctx)):
    await auth_service.change_password(db, auth.user, payload.current_password, payload.new_password,
                                       auth.session.id, ctx)
    return Response(status_code=204)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    rows = await auth_service.list_sessions(db, auth.user.id)
    return [
        SessionOut.model_validate(r).model_copy(update={"current": r.id == auth.session.id}) for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204, dependencies=[Depends(csrf_protect)])
async def revoke(session_id: uuid.UUID, auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db),
                 ctx: RequestContext = Depends(request_ctx)):
    if not await auth_service.revoke_session(db, session_id, auth.user.id):
        raise NotFound("Сессия не найдена")
    await audit.record(db, "auth.session_revoked", user_id=auth.user.id, entity_type="session",
                       entity_id=session_id, ctx=ctx)
    await db.commit()
    return Response(status_code=204)
