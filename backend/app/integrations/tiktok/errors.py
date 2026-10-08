"""TikTok integration errors.

The hierarchy encodes the retry policy:

* ``TikTokTransient`` / ``TikTokRateLimited`` - retry with backoff.
* ``TikTokAuthError`` - access token rejected: refresh once, then re-authorise.
* everything else is permanent for the request that triggered it.
"""

from __future__ import annotations


class TikTokError(Exception):
    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None,
                 log_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.log_id = log_id

    def __str__(self) -> str:
        return self.message


class TikTokTransient(TikTokError):
    """Network failure, timeout or 5xx - safe to retry later.

    ``maybe_sent`` is True when the request may already have reached TikTok
    (e.g. read timeout): non-idempotent calls must not be blindly repeated.
    """

    def __init__(self, message: str, *, maybe_sent: bool = False, **kw) -> None:
        super().__init__(message, **kw)
        self.maybe_sent = maybe_sent


class TikTokRateLimited(TikTokTransient):
    def __init__(self, message: str = "TikTok rate limit exceeded", *, retry_after: float = 60.0, **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class TikTokAuthError(TikTokError):
    """access_token_invalid - token expired or revoked."""


class TikTokScopeError(TikTokError):
    """scope_not_authorized - the user did not grant a required scope."""


class TikTokOAuthError(TikTokError):
    """Token endpoint error (invalid_grant, invalid_request, ...)."""

    @property
    def requires_reauth(self) -> bool:
        return self.code in {"invalid_grant", "invalid_client", "unauthorized_client"}


class TikTokApiError(TikTokError):
    """Permanent API error (invalid_param, spam_risk_*, unaudited client, ...)."""


class UploadUrlExpired(TikTokError):
    """The upload_url returned by init is no longer valid (it lives for one hour)."""


class UploadOffsetMismatch(TikTokError):
    def __init__(self, message: str, *, uploaded_bytes: int | None) -> None:
        super().__init__(message, code="range_mismatch", http_status=416)
        self.uploaded_bytes = uploaded_bytes


# Human readable (Russian) explanations for the codes documented by TikTok.
USER_MESSAGES: dict[str, str] = {
    "access_token_invalid": "Доступ к TikTok истёк или отозван. Подключите аккаунт заново.",
    "scope_not_authorized": "Для этого действия не выдано необходимое разрешение TikTok.",
    "rate_limit_exceeded": "Достигнут лимит запросов TikTok. Повторим автоматически.",
    "invalid_param": "TikTok отклонил параметры публикации.",
    "spam_risk_too_many_posts": "Достигнут дневной лимит публикаций для этого аккаунта TikTok.",
    "spam_risk_user_banned_from_posting": "TikTok запретил этому аккаунту публиковать видео.",
    "reached_active_user_cap": "Достигнут дневной лимит активных пользователей приложения TikTok.",
    "unaudited_client_can_only_post_to_private_accounts": (
        "Приложение ещё не прошло аудит TikTok: публиковать можно только в приватном режиме "
        "(аккаунт должен быть закрытым, видимость «Только я»)."
    ),
    "privacy_level_option_mismatch": "Выбранный уровень приватности недоступен этому аккаунту.",
    "url_ownership_unverified": "Домен источника видео не подтверждён в TikTok.",
}

FAIL_REASON_MESSAGES: dict[str, str] = {
    "file_format_check_failed": "Формат файла не поддерживается TikTok.",
    "duration_check_failed": "Длительность видео не подходит под ограничения TikTok.",
    "frame_rate_check_failed": "Частота кадров видео не подходит (допустимо 23–60 FPS).",
    "picture_size_check_failed": "Разрешение видео не подходит (допустимо 360–4096 px по каждой стороне).",
    "internal": "Внутренняя ошибка TikTok. Попробуйте позже.",
    "video_pull_failed": "TikTok не смог получить видео.",
    "photo_pull_failed": "TikTok не смог получить изображение.",
    "publish_cancelled": "Публикация отменена.",
    "auth_removed": "Пользователь отозвал доступ приложения в TikTok.",
    "spam_risk_too_many_posts": "Достигнут дневной лимит публикаций для этого аккаунта TikTok.",
    "spam_risk_user_banned_from_posting": "TikTok запретил этому аккаунту публиковать видео.",
    "spam_risk_text": "TikTok отклонил описание как потенциальный спам.",
    "spam_risk": "TikTok отклонил публикацию как потенциальный спам.",
}


def user_message(code: str | None, fallback: str) -> str:
    return USER_MESSAGES.get(code or "", fallback)
