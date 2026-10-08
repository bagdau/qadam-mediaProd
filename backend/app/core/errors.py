from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Error that is safe to show to the client."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None,
                 details: Any = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details
        self.headers = headers or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "Не найдено") -> None:
        super().__init__(message)


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Требуется вход в систему") -> None:
        super().__init__(message)


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str = "Слишком много запросов", retry_after: int = 60) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after)})


class UpstreamUnavailable(AppError):
    status_code = 503
    code = "upstream_unavailable"
