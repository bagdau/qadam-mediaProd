from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, Unauthorized, ValidationFailed
from app.core.security import hash_password, hash_token, new_token, verify_password
from app.models import Session, User, UserRole
from app.services import audit
from app.services.audit import RequestContext

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 12


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if password.isdigit() or password.lower() == password and password.isalpha():
        raise ValidationFailed("Пароль слишком простой: добавьте символы разных типов")
    if len(password) > 256:
        raise ValidationFailed("Пароль слишком длинный")


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    display_name: str = "",
    role: UserRole = UserRole.MEMBER,
    ctx: RequestContext = audit.SYSTEM,
) -> User:
    email = normalize_email(email)
    if not _EMAIL_RE.match(email) or len(email) > 320:
        raise ValidationFailed("Некорректный адрес электронной почты")
    validate_password(password)
    user = User(email=email, password_hash=hash_password(password), display_name=display_name.strip()[:120],
                role=role.value)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("Пользователь с таким адресом уже существует", code="user_exists") from exc
    await audit.record(db, "user.created", user_id=user.id, entity_type="user", entity_id=user.id, ctx=ctx,
                       details={"role": role.value})
    await db.commit()
    return user


async def authenticate(db: AsyncSession, email: str, password: str, ctx: RequestContext) -> User:
    """Check credentials with lockout. Errors never reveal whether the e-mail exists."""
    settings = get_settings()
    now = datetime.now(UTC)
    user = (await db.execute(select(User).where(User.email == normalize_email(email)))).scalar_one_or_none()

    if user and user.locked_until and user.locked_until > now:
        await audit.record(db, "auth.login_blocked", user_id=user.id, ctx=ctx)
        await db.commit()
        raise AppError("Слишком много неудачных попыток. Повторите позже.", code="account_locked", status_code=429,
                       headers={"Retry-After": str(int((user.locked_until - now).total_seconds()) + 1)})

    ok = verify_password(password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_count = 0
        await audit.record(db, "auth.login_failed", user_id=user.id if user else None, ctx=ctx,
                           details={"email_known": user is not None})
        await db.commit()
        raise Unauthorized("Неверный адрес почты или пароль")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    return user


async def create_session(db: AsyncSession, user: User, ctx: RequestContext) -> tuple[Session, str]:
    settings = get_settings()
    now = datetime.now(UTC)
    token = new_token(32)
    session = Session(
        user_id=user.id,
        token_hash=hash_token(token),
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        ip_address=ctx.ip,
        user_agent=ctx.user_agent,
    )
    db.add(session)
    await audit.record(db, "auth.login", user_id=user.id, entity_type="session", ctx=ctx)
    await db.commit()
    return session, token


async def resolve_session(db: AsyncSession, token: str) -> tuple[User, Session] | None:
    settings = get_settings()
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(token))
        )
    ).first()
    if not row:
        return None
    session, user = row
    idle_limit = session.last_seen_at + timedelta(hours=settings.session_idle_hours)
    if session.revoked_at or session.expires_at <= now or idle_limit <= now or not user.is_active:
        return None
    if (now - session.last_seen_at).total_seconds() > 60:
        session.last_seen_at = now
        await db.commit()
    return user, session


async def revoke_session(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount > 0


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    now = datetime.now(UTC)
    rows = await db.execute(
        select(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None), Session.expires_at > now)
        .order_by(Session.last_seen_at.desc())
    )
    return list(rows.scalars())


async def change_password(
    db: AsyncSession, user: User, current: str, new: str, keep_session: uuid.UUID, ctx: RequestContext
) -> None:
    if not verify_password(current, user.password_hash):
        await audit.record(db, "auth.password_change_failed", user_id=user.id, ctx=ctx)
        await db.commit()
        raise Forbidden("Текущий пароль указан неверно", code="wrong_password")
    validate_password(new)
    user.password_hash = hash_password(new)
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.id != keep_session, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await audit.record(db, "auth.password_changed", user_id=user.id, ctx=ctx)
    await db.commit()


async def ensure_bootstrap_admin(db: AsyncSession, settings=None) -> None:
    settings = settings or get_settings()
    email, password = settings.bootstrap_admin_email, settings.bootstrap_admin_password.get_secret_value()
    if not email or not password:
        return
    exists = (await db.execute(select(User.id).where(User.email == normalize_email(email)))).first()
    if exists:
        return
    await create_user(db, email, password, display_name="Administrator", role=UserRole.ADMIN)
