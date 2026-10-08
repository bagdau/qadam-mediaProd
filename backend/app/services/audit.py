from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact
from app.models import AuditLog


@dataclass(frozen=True)
class RequestContext:
    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> RequestContext:
        ip = request.client.host if request.client else None
        agent = request.headers.get("user-agent")
        return cls(ip=ip, user_agent=agent[:512] if agent else None)


SYSTEM = RequestContext()


async def record(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    ctx: RequestContext = SYSTEM,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the current transaction (the caller commits)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            ip_address=ctx.ip,
            user_agent=ctx.user_agent,
            details=redact(details) if details else None,
        )
    )
