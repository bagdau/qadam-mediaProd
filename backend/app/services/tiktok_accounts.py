"""TikTok account lifecycle: OAuth connect, token refresh, revoke, rate-limited calls."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.crypto import Crypto
from app.core.errors import AppError, Conflict, NotFound, TooManyRequests, UpstreamUnavailable
from app.core.security import hash_token, new_token
from app.integrations.tiktok.client import CreatorInfo, TikTokClient, TokenSet
from app.integrations.tiktok.errors import (
    TikTokAuthError,
    TikTokError,
    TikTokOAuthError,
    TikTokRateLimited,
    TikTokTransient,
)
from app.integrations.tiktok.rate_limit import CREATOR_INFO, Budget, TikTokRateLimiter
from app.models import ACTIVE_STATUSES, AccountStatus, ConnectedAccount, OAuthState, Publication
from app.services import audit
from app.services.audit import RequestContext

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ReauthRequired(AppError):
    status_code = 409
    code = "reauth_required"

    def __init__(self) -> None:
        super().__init__("Доступ к TikTok недействителен. Подключите аккаунт заново.")


class TikTokAccountService:
    def __init__(self, client: TikTokClient, limiter: TikTokRateLimiter, crypto: Crypto,
                 sessions: async_sessionmaker[AsyncSession], settings: Settings | None = None) -> None:
        self.client = client
        self.limiter = limiter
        self.crypto = crypto
        # Token operations use their own short transactions so that the row lock taken for a
        # refresh never interferes with (or expires objects of) the caller's session.
        self.sessions = sessions
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ queries
    async def get_owned(self, db: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID) -> ConnectedAccount:
        account = (
            await db.execute(
                select(ConnectedAccount).where(ConnectedAccount.id == account_id, ConnectedAccount.user_id == user_id)
            )
        ).scalar_one_or_none()
        if not account:
            raise NotFound("TikTok-аккаунт не найден")
        return account

    async def list_for_user(self, db: AsyncSession, user_id: uuid.UUID) -> list[ConnectedAccount]:
        rows = await db.execute(
            select(ConnectedAccount)
            .where(ConnectedAccount.user_id == user_id)
            .order_by(ConnectedAccount.connected_at.desc())
        )
        return list(rows.scalars())

    # -------------------------------------------------------------------- OAuth
    async def start_oauth(self, db: AsyncSession, user_id: uuid.UUID, ctx: RequestContext) -> str:
        if not self.settings.tiktok_configured:
            raise Conflict("Интеграция TikTok не настроена: задайте TIKTOK_CLIENT_KEY и TIKTOK_CLIENT_SECRET",
                           code="tiktok_not_configured")
        state = new_token(32)
        now = datetime.now(UTC)
        db.add(
            OAuthState(
                state_hash=hash_token(state),
                user_id=user_id,
                expires_at=now + timedelta(seconds=self.settings.oauth_state_ttl_seconds),
            )
        )
        await audit.record(db, "tiktok.oauth_started", user_id=user_id, entity_type="oauth", ctx=ctx)
        await db.commit()
        return self.client.authorization_url(state)

    async def complete_oauth(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
        error_description: str | None,
        ctx: RequestContext,
    ) -> ConnectedAccount:
        """Validate ``state`` (single use, unexpired, bound to the signed-in user), exchange the code
        on the server and store encrypted tokens. Raises ``AppError`` with a stable ``code``."""
        if not state:
            raise AppError("Отсутствует параметр state", code="oauth_state_missing")
        now = datetime.now(UTC)
        # Atomic single-use consumption: only one concurrent callback can win.
        claimed = (
            await db.execute(
                update(OAuthState)
                .where(
                    OAuthState.state_hash == hash_token(state),
                    OAuthState.user_id == user_id,
                    OAuthState.consumed_at.is_(None),
                    OAuthState.expires_at > now,
                )
                .values(consumed_at=now)
                .returning(OAuthState.id)
            )
        ).first()
        await db.commit()
        if not claimed:
            await audit.record(db, "tiktok.oauth_rejected", user_id=user_id, ctx=ctx, details={"reason": "state"})
            await db.commit()
            raise AppError("Проверка state не пройдена или срок действия истёк. Начните подключение заново.",
                           code="oauth_state_invalid")
        if error:
            await audit.record(db, "tiktok.oauth_denied", user_id=user_id, ctx=ctx,
                               details={"error": error, "description": error_description})
            await db.commit()
            raise AppError("TikTok не подтвердил доступ" + (f": {error_description}" if error_description else ""),
                           code="oauth_denied")
        if not code:
            raise AppError("TikTok не вернул код авторизации", code="oauth_code_missing")

        try:
            tokens = await self.client.exchange_code(code)
        except TikTokTransient as exc:
            raise UpstreamUnavailable("TikTok временно недоступен. Повторите подключение.") from exc
        except TikTokError as exc:
            await audit.record(db, "tiktok.oauth_failed", user_id=user_id, ctx=ctx, details={"error": exc.code})
            await db.commit()
            raise AppError("TikTok отклонил код авторизации. Начните подключение заново.",
                           code="oauth_exchange_failed") from exc

        profile: dict = {}
        try:
            if "user.info.basic" in tokens.scopes:
                profile = await self.client.user_info(tokens.access_token)
        except TikTokError:
            logger.warning("user_info failed after oauth")
        account = await self._upsert_account(db, user_id, tokens, profile)
        await audit.record(db, "tiktok.account_connected", user_id=user_id, entity_type="account",
                           entity_id=account.id, ctx=ctx, details={"scopes": tokens.scopes})
        await db.commit()
        return account

    async def _upsert_account(self, db: AsyncSession, user_id: uuid.UUID, tokens: TokenSet,
                              profile: dict) -> ConnectedAccount:
        open_id = tokens.open_id or str(profile.get("open_id") or "")
        if not open_id:
            raise AppError("TikTok не вернул идентификатор аккаунта", code="oauth_no_open_id")
        now = datetime.now(UTC)
        account = (
            await db.execute(
                select(ConnectedAccount)
                .where(
                    ConnectedAccount.user_id == user_id,
                    ConnectedAccount.provider == "tiktok",
                    ConnectedAccount.provider_account_id == open_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None:
            account = ConnectedAccount(user_id=user_id, provider="tiktok", provider_account_id=open_id,
                                       connected_at=now, scopes=[])
            db.add(account)
        account.display_name = profile.get("display_name") or account.display_name
        account.avatar_url = profile.get("avatar_url") or account.avatar_url
        account.username = account.username or profile.get("display_name")
        self._store_tokens(account, tokens)
        account.status = AccountStatus.ACTIVE.value
        account.last_error = None
        account.disconnected_at = None
        account.connected_at = now
        await db.flush()
        return account

    def _store_tokens(self, account: ConnectedAccount, tokens: TokenSet) -> None:
        account.access_token_enc = self.crypto.encrypt(tokens.access_token)
        if tokens.refresh_token:  # TikTok may or may not rotate the refresh token
            account.refresh_token_enc = self.crypto.encrypt(tokens.refresh_token)
            account.refresh_expires_at = tokens.refresh_expires_at
        account.access_expires_at = tokens.access_expires_at
        account.last_refreshed_at = datetime.now(UTC)
        if tokens.scopes:
            account.scopes = tokens.scopes

    # ------------------------------------------------------------------- tokens
    async def access_token(self, account_id: uuid.UUID, *, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing under a row lock when needed.

        Concurrent callers serialize on ``SELECT ... FOR UPDATE``; the second one sees the
        refreshed token and does not hit TikTok again."""
        async with self.sessions() as db:
            account = (
                await db.execute(
                    select(ConnectedAccount).where(ConnectedAccount.id == account_id).with_for_update()
                )
            ).scalar_one_or_none()
            if account is None:
                raise NotFound("TikTok-аккаунт не найден")
            if account.status != AccountStatus.ACTIVE.value or not account.access_token_enc:
                raise ReauthRequired()

            now = datetime.now(UTC)
            leeway = timedelta(seconds=self.settings.tiktok_refresh_leeway_seconds)
            needs = force_refresh or account.access_expires_at is None or account.access_expires_at - leeway <= now
            if not needs:
                return self.crypto.decrypt(account.access_token_enc)
            try:
                token = await self._refresh_locked(db, account)
                await db.commit()
            except BaseException:
                await db.rollback()  # never leave the row lock held after a failure
                raise
            return token

    async def _refresh_locked(self, db: AsyncSession, account: ConnectedAccount) -> str:
        if not account.refresh_token_enc or (
            account.refresh_expires_at and account.refresh_expires_at <= datetime.now(UTC)
        ):
            await self._mark_reauth(db, account, "refresh token expired")
            raise ReauthRequired()
        try:
            tokens = await self.client.refresh(self.crypto.decrypt(account.refresh_token_enc))
        except TikTokOAuthError as exc:
            if exc.requires_reauth:
                await self._mark_reauth(db, account, exc.code or "oauth_error")
                raise ReauthRequired() from exc
            raise
        self._store_tokens(account, tokens)
        account.last_error = None
        return tokens.access_token

    async def _mark_reauth(self, db: AsyncSession, account: ConnectedAccount, reason: str) -> None:
        account.status = AccountStatus.NEEDS_REAUTH.value
        account.last_error = reason[:500]
        await audit.record(db, "tiktok.reauth_required", user_id=account.user_id, entity_type="account",
                           entity_id=account.id, details={"reason": reason})
        await db.commit()

    async def refresh_account(self, account_id: uuid.UUID) -> None:
        await self.access_token(account_id, force_refresh=True)

    async def call(
        self,
        account_id: uuid.UUID,
        budget: Budget,
        operation: Callable[[str], Awaitable[T]],
    ) -> T:
        """Rate-limited call with one transparent refresh+retry on ``access_token_invalid``."""
        wait = await self.limiter.acquire(str(account_id), budget)
        if wait:
            raise TikTokRateLimited(retry_after=wait)
        token = await self.access_token(account_id)
        try:
            return await operation(token)
        except TikTokAuthError:
            token = await self.access_token(account_id, force_refresh=True)
            try:
                return await operation(token)
            except TikTokAuthError as exc:
                async with self.sessions() as db:
                    account = await db.get(ConnectedAccount, account_id)
                    if account:
                        await self._mark_reauth(db, account, "access_token_invalid")
                raise ReauthRequired() from exc

    async def creator_info(self, account_id: uuid.UUID) -> CreatorInfo:
        return await self.call(account_id, CREATOR_INFO, lambda tok: self.client.creator_info(tok))

    # --------------------------------------------------------------- disconnect
    async def disconnect(self, db: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID,
                         ctx: RequestContext) -> None:
        account = await self.get_owned(db, user_id, account_id)
        active = (
            await db.execute(
                select(Publication.id)
                .where(Publication.account_id == account.id,
                       Publication.status.in_([s.value for s in ACTIVE_STATUSES]))
                .limit(1)
            )
        ).first()
        if active:
            raise Conflict("Есть незавершённые публикации. Дождитесь их завершения или отмените.",
                           code="account_busy")
        revoked_remote = False
        if account.access_token_enc:
            try:
                await self.client.revoke(self.crypto.decrypt(account.access_token_enc))
                revoked_remote = True
            except TikTokError as exc:
                # Local credentials are removed regardless; the user can also revoke in TikTok settings.
                logger.warning("tiktok revoke failed: %s", exc.code or type(exc).__name__)
        account.access_token_enc = None
        account.refresh_token_enc = None
        account.access_expires_at = None
        account.refresh_expires_at = None
        account.status = AccountStatus.REVOKED.value
        account.disconnected_at = datetime.now(UTC)
        await audit.record(db, "tiktok.account_disconnected", user_id=user_id, entity_type="account",
                           entity_id=account.id, ctx=ctx, details={"revoked_remote": revoked_remote})
        await db.commit()

    # ------------------------------------------------------------- maintenance
    async def refresh_expiring(self, within: timedelta = timedelta(hours=2)) -> dict[str, int]:
        horizon = datetime.now(UTC) + within
        async with self.sessions() as db:
            ids = (
                await db.execute(
                    select(ConnectedAccount.id).where(
                        ConnectedAccount.status == AccountStatus.ACTIVE.value,
                        ConnectedAccount.refresh_token_enc.is_not(None),
                        ConnectedAccount.access_expires_at < horizon,
                    )
                )
            ).scalars().all()
        stats = {"refreshed": 0, "failed": 0, "reauth": 0}
        for account_id in ids:
            try:
                await self.access_token(account_id, force_refresh=True)
                stats["refreshed"] += 1
            except ReauthRequired:
                stats["reauth"] += 1
            except (TikTokError, AppError):
                stats["failed"] += 1
        return stats


def to_http_error(exc: TikTokError) -> AppError:
    """Translate integration errors raised in request handlers to client-safe errors."""
    if isinstance(exc, TikTokRateLimited):
        return TooManyRequests("Достигнут лимит запросов TikTok. Повторите через минуту.",
                               retry_after=int(exc.retry_after))
    if isinstance(exc, TikTokTransient):
        return UpstreamUnavailable("TikTok временно недоступен. Повторите попытку позже.")
    return AppError(exc.message, code=f"tiktok_{exc.code or 'error'}", status_code=502)
