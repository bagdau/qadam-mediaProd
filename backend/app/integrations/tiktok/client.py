"""Typed async client for the TikTok Login Kit and Content Posting APIs.

Endpoints (verified against developers.tiktok.com, 2026-10-09):

* ``GET  https://www.tiktok.com/v2/auth/authorize/``
* ``POST {api}/oauth/token/`` (authorization_code / refresh_token), ``POST {api}/oauth/revoke/``
* ``GET  {api}/user/info/``
* ``POST {api}/post/publish/creator_info/query/``
* ``POST {api}/post/publish/video/init/``        (Direct Post, ``video.publish``)
* ``POST {api}/post/publish/inbox/video/init/``  (upload to inbox, ``video.upload``)
* ``PUT  {upload_url}`` (chunked, Content-Range)
* ``POST {api}/post/publish/status/fetch/``

The client never logs tokens or response bodies and never raises raw httpx
errors: everything is mapped to ``errors.TikTokError`` subclasses.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings
from app.integrations.tiktok.chunks import ChunkPlan
from app.integrations.tiktok.errors import (
    TikTokApiError,
    TikTokAuthError,
    TikTokError,
    TikTokOAuthError,
    TikTokRateLimited,
    TikTokScopeError,
    TikTokTransient,
    UploadOffsetMismatch,
    UploadUrlExpired,
    user_message,
)

logger = logging.getLogger(__name__)

_READ_PIECE = 1024 * 1024
_JSON_HEADERS = {"Content-Type": "application/json; charset=UTF-8"}


@dataclass(frozen=True)
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_expires_at: datetime
    open_id: str
    scopes: list[str]


@dataclass(frozen=True)
class CreatorInfo:
    username: str
    nickname: str
    avatar_url: str | None
    privacy_level_options: list[str]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_video_post_duration_sec: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "nickname": self.nickname,
            "avatar_url": self.avatar_url,
            "privacy_level_options": self.privacy_level_options,
            "comment_disabled": self.comment_disabled,
            "duet_disabled": self.duet_disabled,
            "stitch_disabled": self.stitch_disabled,
            "max_video_post_duration_sec": self.max_video_post_duration_sec,
        }


@dataclass(frozen=True)
class InitResult:
    publish_id: str
    upload_url: str = field(repr=False)


@dataclass(frozen=True)
class PublishStatus:
    status: str
    fail_reason: str | None
    post_ids: list[str]
    uploaded_bytes: int | None


@dataclass(frozen=True)
class PostInfo:
    title: str
    privacy_level: str
    disable_comment: bool
    disable_duet: bool
    disable_stitch: bool
    cover_timestamp_ms: int = 0
    brand_content_toggle: bool = False
    brand_organic_toggle: bool = False
    is_aigc: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "privacy_level": self.privacy_level,
            "disable_comment": self.disable_comment,
            "disable_duet": self.disable_duet,
            "disable_stitch": self.disable_stitch,
            "video_cover_timestamp_ms": self.cover_timestamp_ms,
            "brand_content_toggle": self.brand_content_toggle,
            "brand_organic_toggle": self.brand_organic_toggle,
            "is_aigc": self.is_aigc,
        }


def _now() -> datetime:
    return datetime.now(UTC)


class TikTokClient:
    def __init__(self, settings: Settings | None = None, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.tiktok_http_timeout, connect=10.0),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> TikTokClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ OAuth
    def authorization_url(self, state: str) -> str:
        s = self._settings
        query = urlencode(
            {
                "client_key": s.tiktok_client_key,
                "response_type": "code",
                "scope": ",".join(s.scope_list),
                "redirect_uri": s.tiktok_redirect_uri,
                "state": state,
            }
        )
        return f"{s.tiktok_authorize_url}?{query}"

    async def exchange_code(self, code: str) -> TokenSet:
        s = self._settings
        body = await self._oauth_post(
            "/oauth/token/",
            {
                "client_key": s.tiktok_client_key,
                "client_secret": s.tiktok_client_secret.get_secret_value(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": s.tiktok_redirect_uri,
            },
        )
        return self._token_set(body)

    async def refresh(self, refresh_token: str) -> TokenSet:
        s = self._settings
        body = await self._oauth_post(
            "/oauth/token/",
            {
                "client_key": s.tiktok_client_key,
                "client_secret": s.tiktok_client_secret.get_secret_value(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        return self._token_set(body)

    async def revoke(self, access_token: str) -> None:
        s = self._settings
        await self._oauth_post(
            "/oauth/revoke/",
            {
                "client_key": s.tiktok_client_key,
                "client_secret": s.tiktok_client_secret.get_secret_value(),
                "token": access_token,
            },
            expect_body=False,
        )

    # --------------------------------------------------------------- user info
    async def user_info(self, access_token: str) -> dict[str, Any]:
        body = await self._api(
            "GET",
            "/user/info/",
            access_token,
            params={"fields": "open_id,union_id,avatar_url,display_name"},
        )
        return (body.get("data") or {}).get("user") or {}

    async def creator_info(self, access_token: str) -> CreatorInfo:
        body = await self._api("POST", "/post/publish/creator_info/query/", access_token)
        data = body.get("data") or {}
        return CreatorInfo(
            username=str(data.get("creator_username") or ""),
            nickname=str(data.get("creator_nickname") or data.get("creator_username") or ""),
            avatar_url=data.get("creator_avatar_url"),
            privacy_level_options=list(data.get("privacy_level_options") or []),
            comment_disabled=bool(data.get("comment_disabled", False)),
            duet_disabled=bool(data.get("duet_disabled", False)),
            stitch_disabled=bool(data.get("stitch_disabled", False)),
            max_video_post_duration_sec=data.get("max_video_post_duration_sec"),
        )

    # --------------------------------------------------------------- publishing
    async def init_direct_post(self, access_token: str, post: PostInfo, plan: ChunkPlan) -> InitResult:
        body = await self._api(
            "POST",
            "/post/publish/video/init/",
            access_token,
            json={"post_info": post.as_payload(), "source_info": _source_info(plan)},
        )
        return self._checked_init(body)

    async def init_inbox_upload(self, access_token: str, plan: ChunkPlan) -> InitResult:
        body = await self._api(
            "POST",
            "/post/publish/inbox/video/init/",
            access_token,
            json={"source_info": _source_info(plan)},
        )
        return self._checked_init(body)

    async def upload_chunk(
        self, upload_url: str, path: Path, first: int, last: int, total: int, content_type: str
    ) -> int:
        """PUT bytes ``first..last`` of ``path``. Returns 206 (more expected) or 201 (complete)."""
        length = last - first + 1
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(length),
            "Content-Range": f"bytes {first}-{last}/{total}",
        }
        try:
            response = await self._http.put(
                upload_url,
                content=_iter_file(path, first, length),
                headers=headers,
                timeout=httpx.Timeout(600.0, connect=15.0),
            )
        except httpx.HTTPError as exc:
            raise TikTokTransient(f"Сбой загрузки видео в TikTok ({type(exc).__name__})") from exc
        status = response.status_code
        if status in (201, 206):
            return status
        if status == 416:
            raise UploadOffsetMismatch("Смещение загрузки не совпадает", uploaded_bytes=_uploaded_from_range(response))
        if status in (403, 404):
            raise UploadUrlExpired("Ссылка загрузки TikTok недействительна или истекла", http_status=status)
        if status == 429:
            raise TikTokRateLimited(retry_after=_retry_after(response), http_status=status)
        if status >= 500:
            raise TikTokTransient(f"TikTok вернул {status} при загрузке", http_status=status)
        raise TikTokApiError(f"TikTok отклонил загрузку (HTTP {status})", http_status=status)

    async def fetch_status(self, access_token: str, publish_id: str) -> PublishStatus:
        body = await self._api(
            "POST", "/post/publish/status/fetch/", access_token, json={"publish_id": publish_id}
        )
        data = body.get("data") or {}
        ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
        return PublishStatus(
            status=str(data.get("status") or ""),
            fail_reason=data.get("fail_reason") or None,
            post_ids=[str(i) for i in ids],
            uploaded_bytes=data.get("uploaded_bytes"),
        )

    # ------------------------------------------------------------------ plumbing
    async def _oauth_post(self, path: str, form: dict[str, str], *, expect_body: bool = True) -> dict[str, Any]:
        url = self._settings.tiktok_api_base + path
        try:
            response = await self._http.post(
                url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
            )
        except httpx.HTTPError as exc:
            raise TikTokTransient(f"Не удалось связаться с TikTok ({type(exc).__name__})") from exc
        body = _json(response)
        if response.status_code == 429:
            raise TikTokRateLimited(retry_after=_retry_after(response), http_status=429)
        if response.status_code >= 500:
            raise TikTokTransient(f"TikTok недоступен (HTTP {response.status_code})", http_status=response.status_code)
        error = body.get("error")
        if isinstance(error, str) and error:
            raise TikTokOAuthError(
                str(body.get("error_description") or error),
                code=error,
                http_status=response.status_code,
                log_id=body.get("log_id"),
            )
        if not response.is_success:
            raise TikTokOAuthError(f"OAuth HTTP {response.status_code}", http_status=response.status_code)
        if expect_body and "access_token" not in body:
            raise TikTokOAuthError("В ответе TikTok нет access_token", code="malformed_response")
        return body

    async def _api(
        self,
        method: str,
        path: str,
        access_token: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        if method != "GET":
            headers.update(_JSON_HEADERS)
        try:
            response = await self._http.request(
                method, self._settings.tiktok_api_base + path, params=params, json=json, headers=headers
            )
        except httpx.HTTPError as exc:
            not_sent = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
            raise TikTokTransient(
                f"Не удалось связаться с TikTok ({type(exc).__name__})", maybe_sent=not not_sent
            ) from exc
        return _raise_for_api_error(response, path)

    def _checked_init(self, body: dict[str, Any]) -> InitResult:
        result = _init_result(body)
        if self._settings.is_production and not result.upload_url.lower().startswith("https://"):
            raise TikTokApiError("TikTok вернул небезопасный адрес загрузки", code="insecure_upload_url")
        return result

    @staticmethod
    def _token_set(body: dict[str, Any]) -> TokenSet:
        now = _now()
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", ""),
            access_expires_at=now + timedelta(seconds=int(body.get("expires_in", 86400))),
            refresh_expires_at=now + timedelta(seconds=int(body.get("refresh_expires_in", 31536000))),
            open_id=str(body.get("open_id", "")),
            scopes=[s for s in str(body.get("scope", "")).split(",") if s],
        )


def _source_info(plan: ChunkPlan) -> dict[str, Any]:
    return {
        "source": "FILE_UPLOAD",
        "video_size": plan.video_size,
        "chunk_size": plan.chunk_size,
        "total_chunk_count": plan.total_chunks,
    }


def _init_result(body: dict[str, Any]) -> InitResult:
    data = body.get("data") or {}
    publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
    if not publish_id or not upload_url:
        raise TikTokApiError("TikTok не вернул publish_id/upload_url", code="malformed_response")
    return InitResult(publish_id=str(publish_id), upload_url=str(upload_url))


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(1.0, float(response.headers.get("Retry-After", "60")))
    except ValueError:
        return 60.0


def _uploaded_from_range(response: httpx.Response) -> int | None:
    match = re.match(r"bytes\s+\d+-(\d+)/\d+", response.headers.get("Content-Range", ""))
    return int(match.group(1)) + 1 if match else None


def _raise_for_api_error(response: httpx.Response, path: str) -> dict[str, Any]:
    body = _json(response)
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = (error or {}).get("code")
    message = (error or {}).get("message") or ""
    log_id = (error or {}).get("log_id") or (error or {}).get("logid")
    status = response.status_code
    meta = {"code": code, "http_status": status, "log_id": log_id}

    if status == 429 or code == "rate_limit_exceeded":
        raise TikTokRateLimited(user_message("rate_limit_exceeded", message), retry_after=_retry_after(response), **meta)
    if status >= 500:
        raise TikTokTransient(f"TikTok временно недоступен (HTTP {status})", **meta)
    if code == "access_token_invalid" or (status == 401 and code != "scope_not_authorized"):
        raise TikTokAuthError(user_message("access_token_invalid", message), **meta)
    if code == "scope_not_authorized":
        raise TikTokScopeError(user_message(code, message), **meta)
    if code in (None, "ok") and response.is_success:
        return body
    if code in (None, "ok"):
        raise TikTokApiError(f"TikTok вернул HTTP {status}", **meta)
    logger.warning("tiktok api error", extra={"path": path})
    raise TikTokApiError(user_message(code, message or str(code)), **meta)


async def _iter_file(path: Path, first: int, length: int) -> AsyncIterator[bytes]:
    remaining = length

    def _open() -> Any:
        handle = open(path, "rb")  # noqa: SIM115 - closed in finally below
        handle.seek(first)
        return handle

    handle = await asyncio.to_thread(_open)
    try:
        while remaining > 0:
            piece = await asyncio.to_thread(handle.read, min(_READ_PIECE, remaining))
            if not piece:
                raise TikTokError("Файл видео короче ожидаемого размера")
            remaining -= len(piece)
            yield piece
    finally:
        await asyncio.to_thread(handle.close)
