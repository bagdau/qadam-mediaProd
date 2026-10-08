from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, csrf_protect, get_db, media_service, request_ctx, require_auth, user_rate_limit
from app.models import MediaAsset
from app.schemas.core import MediaOut
from app.services.audit import RequestContext
from app.services.media import MediaService

router = APIRouter(prefix="/media", tags=["media"])


@router.post("", response_model=MediaOut, status_code=201,
             dependencies=[Depends(csrf_protect), Depends(user_rate_limit("media_upload", 30, 3600))])
async def upload(
    video: UploadFile = File(...),
    duration_seconds: float | None = Form(default=None, ge=0, le=14400),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    svc: MediaService = Depends(media_service),
    ctx: RequestContext = Depends(request_ctx),
):
    return await svc.save_upload(db, auth.user.id, video, client_duration=duration_seconds, ctx=ctx)


@router.get("", response_model=list[MediaOut])
async def list_media(auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(MediaAsset)
        .where(MediaAsset.user_id == auth.user.id, MediaAsset.status == "ready")
        .order_by(MediaAsset.created_at.desc())
        .limit(100)
    )
    return list(rows.scalars())


@router.get("/{media_id}", response_model=MediaOut)
async def get_media(media_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                    db: AsyncSession = Depends(get_db), svc: MediaService = Depends(media_service)):
    return await svc.get_owned(db, auth.user.id, media_id)


@router.delete("/{media_id}", status_code=204, dependencies=[Depends(csrf_protect)])
async def delete_media(media_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                       db: AsyncSession = Depends(get_db), svc: MediaService = Depends(media_service),
                       ctx: RequestContext = Depends(request_ctx)):
    await svc.delete(db, auth.user.id, media_id, ctx)
    return Response(status_code=204)
