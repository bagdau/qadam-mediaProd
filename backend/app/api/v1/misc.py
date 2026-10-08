from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_auth, settings_dep
from app.core.config import Settings
from app.models import (
    ACTIVE_STATUSES,
    AccountStatus,
    AuditLog,
    ConnectedAccount,
    Publication,
    PublicationStatus,
)
from app.schemas.core import AuditLogOut, AuditPage, DashboardOut, MetaOut
from app.services.mediainfo import ALLOWED_TYPES

router = APIRouter(tags=["misc"])


@router.get("/meta", response_model=MetaOut)
async def meta(settings: Settings = Depends(settings_dep)):
    return MetaOut(
        tiktok_configured=settings.tiktok_configured,
        tiktok_client_audited=settings.tiktok_client_audited,
        scopes=settings.scope_list,
        max_video_mb=settings.max_video_mb,
        allowed_content_types=list(ALLOWED_TYPES),
        allow_registration=settings.allow_registration,
    )


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    uid = auth.user.id
    accounts = (await db.execute(select(ConnectedAccount.status, func.count()).where(
        ConnectedAccount.user_id == uid, ConnectedAccount.status != AccountStatus.REVOKED.value
    ).group_by(ConnectedAccount.status))).all()
    by_status = dict((await db.execute(
        select(Publication.status, func.count()).where(Publication.user_id == uid).group_by(Publication.status)
    )).all())
    since = datetime.now(UTC) - timedelta(days=7)
    day = func.date_trunc("day", Publication.created_at)
    daily_rows = (await db.execute(
        select(day, Publication.status, func.count()).where(Publication.user_id == uid, Publication.created_at >= since)
        .group_by(day, Publication.status).order_by(day)
    )).all()
    daily: dict[str, dict] = {}
    for d, status, count in daily_rows:
        entry = daily.setdefault(d.date().isoformat(), {"date": d.date().isoformat(), "total": 0, "published": 0})
        entry["total"] += count
        if status in (PublicationStatus.PUBLISHED.value, PublicationStatus.INBOX_DELIVERED.value):
            entry["published"] += count
    recent = (await db.execute(
        select(Publication).where(Publication.user_id == uid).order_by(Publication.created_at.desc()).limit(5)
    )).scalars().all()
    active = {s.value for s in ACTIVE_STATUSES}
    return DashboardOut(
        accounts_total=sum(c for _, c in accounts),
        accounts_needing_attention=sum(c for s, c in accounts if s != AccountStatus.ACTIVE.value),
        publications_total=sum(by_status.values()),
        publications_by_status=by_status,
        in_progress=sum(c for s, c in by_status.items() if s in active),
        published_last_7_days=sum(e["published"] for e in daily.values()),
        daily=list(daily.values()),
        recent=[{"id": str(p.id), "title": p.title[:80], "status": p.status, "created_at": p.created_at.isoformat(),
                 "privacy_level": p.privacy_level} for p in recent],
    )


@router.get("/audit-logs", response_model=AuditPage)
async def audit_logs(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                     auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    where = AuditLog.user_id == auth.user.id
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(where))).scalar_one()
    rows = (await db.execute(select(AuditLog).where(where).order_by(AuditLog.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return AuditPage(items=[AuditLogOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)
