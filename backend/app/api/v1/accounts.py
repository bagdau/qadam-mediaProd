from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, csrf_protect, get_db, request_ctx, require_auth, tiktok_service, user_rate_limit
from app.integrations.tiktok.errors import TikTokError
from app.schemas.core import AccountOut, CreatorInfoOut, OAuthStartOut
from app.services.audit import RequestContext
from app.services.tiktok_accounts import ReauthRequired, TikTokAccountService, to_http_error

router = APIRouter(tags=["tiktok"])


@router.post("/tiktok/oauth/start", response_model=OAuthStartOut,
             dependencies=[Depends(csrf_protect), Depends(user_rate_limit("oauth_start", 20, 600))])
async def oauth_start(auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db),
                      svc: TikTokAccountService = Depends(tiktok_service), ctx: RequestContext = Depends(request_ctx)):
    url = await svc.start_oauth(db, auth.user.id, ctx)
    return OAuthStartOut(authorization_url=url)


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db),
                        svc: TikTokAccountService = Depends(tiktok_service)):
    return await svc.list_for_user(db, auth.user.id)


@router.get("/accounts/{account_id}", response_model=AccountOut)
async def get_account(account_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                      db: AsyncSession = Depends(get_db), svc: TikTokAccountService = Depends(tiktok_service)):
    return await svc.get_owned(db, auth.user.id, account_id)


@router.get("/accounts/{account_id}/creator-info", response_model=CreatorInfoOut,
            dependencies=[Depends(user_rate_limit("creator_info", 60, 60))])
async def creator_info(account_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                       db: AsyncSession = Depends(get_db), svc: TikTokAccountService = Depends(tiktok_service)):
    account = await svc.get_owned(db, auth.user.id, account_id)
    try:
        info = await svc.creator_info(account.id)
    except ReauthRequired:
        raise
    except TikTokError as exc:
        raise to_http_error(exc) from exc
    return CreatorInfoOut(**info.as_dict())


@router.post("/accounts/{account_id}/refresh", response_model=AccountOut,
             dependencies=[Depends(csrf_protect), Depends(user_rate_limit("account_refresh", 10, 600))])
async def refresh_account(account_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                          db: AsyncSession = Depends(get_db), svc: TikTokAccountService = Depends(tiktok_service)):
    account = await svc.get_owned(db, auth.user.id, account_id)
    try:
        await svc.refresh_account(account.id)
    except TikTokError as exc:
        raise to_http_error(exc) from exc
    await db.refresh(account)
    return account


@router.delete("/accounts/{account_id}", status_code=204, dependencies=[Depends(csrf_protect)])
async def disconnect_account(account_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                             db: AsyncSession = Depends(get_db), svc: TikTokAccountService = Depends(tiktok_service),
                             ctx: RequestContext = Depends(request_ctx)):
    await svc.disconnect(db, auth.user.id, account_id, ctx)
    return Response(status_code=204)
