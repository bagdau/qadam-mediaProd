"""Browser-facing OAuth callback.

TikTok redirects the user's browser here (``TIKTOK_REDIRECT_URI`` must point at this path), so it
is a GET without CSRF token; safety comes from the single-use ``state`` that is bound to the
signed-in user and verified server-side. The code exchange happens on the server.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, optional_auth, request_ctx, settings_dep, tiktok_service
from app.core.config import Settings
from app.core.errors import AppError
from app.services.audit import RequestContext
from app.services.tiktok_accounts import TikTokAccountService

router = APIRouter(tags=["oauth"])


def _redirect(settings: Settings, path: str, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    response = RedirectResponse(f"{settings.public_url.rstrip('/')}{path}{query}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/oauth/tiktok/callback", include_in_schema=False)
async def tiktok_callback(
    code: str | None = Query(default=None, max_length=2048),
    state: str | None = Query(default=None, max_length=256),
    scopes: str | None = Query(default=None, max_length=1024),
    error: str | None = Query(default=None, max_length=128),
    error_description: str | None = Query(default=None, max_length=512),
    auth: AuthContext | None = Depends(optional_auth),
    db: AsyncSession = Depends(get_db),
    svc: TikTokAccountService = Depends(tiktok_service),
    ctx: RequestContext = Depends(request_ctx),
    settings: Settings = Depends(settings_dep),
):
    if auth is None:
        return _redirect(settings, "/login", oauth_error="session_required")
    try:
        account = await svc.complete_oauth(db, auth.user.id, code=code, state=state, error=error,
                                           error_description=error_description, ctx=ctx)
    except AppError as exc:
        return _redirect(settings, "/accounts", oauth_error=exc.code)
    return _redirect(settings, "/accounts", connected=str(account.id))
