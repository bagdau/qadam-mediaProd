from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthContext,
    csrf_protect,
    get_db,
    publication_service,
    request_ctx,
    require_auth,
    user_rate_limit,
)
from app.core.errors import ValidationFailed
from app.models import ConnectedAccount, MediaAsset, PublicationStatus
from app.schemas.publication import (
    PublicationCreate,
    PublicationDetail,
    PublicationEventOut,
    PublicationOut,
    PublicationPage,
    RetryRequest,
)
from app.services.audit import RequestContext
from app.services.publications import PublicationService

router = APIRouter(prefix="/publications", tags=["publications"])
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


@router.post("", response_model=PublicationOut, status_code=201,
             dependencies=[Depends(csrf_protect), Depends(user_rate_limit("publish", 30, 600))])
async def create_publication(
    payload: PublicationCreate,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    svc: PublicationService = Depends(publication_service),
    ctx: RequestContext = Depends(request_ctx),
):
    """Creates a publication and queues it. Requires an ``Idempotency-Key`` header: a repeated key
    (double click, network retry) returns the original publication with HTTP 200 instead of creating a duplicate."""
    if not idempotency_key or not _KEY_RE.match(idempotency_key):
        raise ValidationFailed("Заголовок Idempotency-Key обязателен (8–128 символов: буквы, цифры, - _ : .)",
                               code="idempotency_key_required")
    pub, created = await svc.create(db, auth.user.id, payload, idempotency_key, ctx)
    if not created:
        response.status_code = 200
    return pub


@router.get("", response_model=PublicationPage)
async def list_publications(
    status: PublicationStatus | None = None,
    account_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    svc: PublicationService = Depends(publication_service),
):
    items, total = await svc.list_page(db, auth.user.id, status=status.value if status else None,
                                       account_id=account_id, limit=limit, offset=offset)
    return PublicationPage(items=[PublicationOut.model_validate(i) for i in items], total=total, limit=limit,
                           offset=offset)


@router.get("/{publication_id}", response_model=PublicationDetail)
async def get_publication(publication_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                          db: AsyncSession = Depends(get_db), svc: PublicationService = Depends(publication_service)):
    pub = await svc.get_owned(db, auth.user.id, publication_id)
    events = await svc.events(db, pub.id)
    media = await db.get(MediaAsset, pub.media_id)
    account = await db.get(ConnectedAccount, pub.account_id)
    base = PublicationOut.model_validate(pub).model_dump()
    return PublicationDetail(
        **base,
        events=[PublicationEventOut.model_validate(e) for e in events],
        media_filename=media.original_filename if media else None,
        media_size_bytes=media.size_bytes if media else None,
        account_username=(account.display_name or account.username) if account else None,
    )


@router.post("/{publication_id}/cancel", response_model=PublicationOut, dependencies=[Depends(csrf_protect)])
async def cancel_publication(publication_id: uuid.UUID, auth: AuthContext = Depends(require_auth),
                             db: AsyncSession = Depends(get_db),
                             svc: PublicationService = Depends(publication_service),
                             ctx: RequestContext = Depends(request_ctx)):
    return await svc.cancel(db, auth.user.id, publication_id, ctx)


@router.post("/{publication_id}/retry", response_model=PublicationOut, dependencies=[Depends(csrf_protect)])
async def retry_publication(publication_id: uuid.UUID, payload: RetryRequest | None = None,
                            auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db),
                            svc: PublicationService = Depends(publication_service),
                            ctx: RequestContext = Depends(request_ctx)):
    payload = payload or RetryRequest()
    return await svc.retry(db, auth.user.id, publication_id, payload.confirm_duplicate_risk, ctx)
