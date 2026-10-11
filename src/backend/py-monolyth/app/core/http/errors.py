"""Доменные ошибки и коды ошибок shared kernel (SYS-03-R7, R8, R17–R19).

Модуль объявляет свои ошибки в `app/modules/<module>/public/errors.py` наследниками
`DomainError` с атрибутами `code` (`<module>.<error_name>`) и `http_status`; обработчик
shared kernel превращает их в конверт `ErrorResponseV1`. `message` — английский текст для
разработчика (SYS-07-R12), пользователю показывается перевод по `code`.
"""

import math
from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Any, ClassVar

from app.core.dao.caching import RateLimitResult


class DomainError(Exception):
    """Базовая доменная ошибка с HTTP-статусом и кодом.

    Подклассы задают атрибуты класса `code`, `http_status`, `message` и, при необходимости,
    `hidden_details` — ключи `details`, которые не отдаются клиенту вне `DEBUG_MODE`.

    Args:
        message: текст для разработчика (по умолчанию — `message` класса).
        code: код ошибки (по умолчанию — `code` класса).
        status: HTTP-статус (по умолчанию — `http_status` класса).
        details: детали ошибки.
        headers: дополнительные заголовки ответа.
        **extra_details: детали ошибки именованными аргументами (объединяются с `details`).
    """

    code: ClassVar[str] = "core.internal"
    http_status: ClassVar[int] = 500
    message: ClassVar[str] = "Internal server error"
    hidden_details: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        **extra_details: Any,
    ) -> None:
        """Собирает код, статус, детали и заголовки ошибки."""
        self.error_code = code or type(self).code
        self.status = status or type(self).http_status
        self.error_message = message or type(self).message
        self.details: dict[str, Any] = {**(details or {}), **extra_details}
        self.headers: dict[str, str] = dict(headers or {})
        super().__init__(f"{self.error_code}: {self.error_message}")


class BadRequestError(DomainError):
    """Некорректный заголовок или query-параметр вне схемы тела."""

    code = "core.bad_request"
    http_status = 400
    message = "Bad request"


class InvalidCursorError(BadRequestError):
    """Невалидный курсор пагинации или курсор другой сортировки (SYS-03-R12)."""

    code = "core.invalid_cursor"
    message = "Invalid pagination cursor"


class UnauthenticatedError(DomainError):
    """Нет действительного токена или сессия отозвана; ответ содержит `WWW-Authenticate: Bearer`."""

    code = "core.unauthenticated"
    http_status = 401
    message = "Authentication required"

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        """Добавляет заголовок `WWW-Authenticate: Bearer`."""
        headers = {"WWW-Authenticate": "Bearer", **kwargs.pop("headers", {})}
        super().__init__(message, headers=headers, **kwargs)


class ForbiddenError(DomainError):
    """Нет права на действие (матрица SYS-06); недостающие права клиенту не раскрываются."""

    code = "core.forbidden"
    http_status = 403
    message = "Forbidden"
    hidden_details = ("missing_permissions",)


class NotFoundError(DomainError):
    """Ресурс не найден или его существование скрывается (SYS-03-R22)."""

    code = "core.not_found"
    http_status = 404
    message = "Resource not found"


class MethodNotAllowedError(DomainError):
    """Метод не поддерживается путём."""

    code = "core.method_not_allowed"
    http_status = 405
    message = "Method not allowed"


class VersionConflictError(DomainError):
    """`version` в запросе не совпадает с текущей (SYS-03-R17); `details.current_version`."""

    code = "core.version_conflict"
    http_status = 409
    message = "Resource was modified by another request"

    def __init__(self, current_version: int | None = None, **kwargs: Any) -> None:
        """Добавляет `current_version` в детали, если она известна."""
        if current_version is not None:
            kwargs["current_version"] = current_version
        super().__init__(**kwargs)


class RequestInProgressError(DomainError):
    """Повтор запроса с тем же `Idempotency-Key` до завершения первого (SYS-03-R18)."""

    code = "core.request_in_progress"
    http_status = 409
    message = "Request with this Idempotency-Key is still in progress"

    def __init__(self, **kwargs: Any) -> None:
        """Добавляет заголовок `Retry-After: 1`."""
        super().__init__(headers={"Retry-After": "1"}, **kwargs)


class PayloadTooLargeError(DomainError):
    """Тело JSON больше `HTTP_MAX_JSON_BODY_BYTES` (SYS-03-R26)."""

    code = "core.payload_too_large"
    http_status = 413
    message = "Payload too large"


class UnsupportedMediaTypeError(DomainError):
    """`Content-Type` не `application/json` там, где ожидается JSON."""

    code = "core.unsupported_media_type"
    http_status = 415
    message = "Unsupported media type"


class ValidationFailedError(DomainError):
    """Ошибка валидации; `details.errors` — элементы `{loc, type, msg, ctx}` (SYS-03-R9)."""

    code = "core.validation_failed"
    http_status = 422
    message = "Request validation failed"

    @classmethod
    def for_field(cls, loc: list[str | int], error_type: str, msg: str, **ctx: Any) -> ValidationFailedError:
        """Ошибка валидации одного поля в формате `RequestValidationError.errors()`."""
        return cls(details={"errors": [{"loc": loc, "type": error_type, "msg": msg, "ctx": ctx}]})


class IdempotencyKeyReusedError(DomainError):
    """Тот же `Idempotency-Key` с другим телом запроса (SYS-03-R18)."""

    code = "core.idempotency_key_reused"
    http_status = 422
    message = "Idempotency-Key was already used with a different request body"


class RateLimitedError(DomainError):
    """Превышен лимит запросов (SYS-03-R19): заголовок `Retry-After`, детали `scope` и `retry_after_seconds`."""

    code = "core.rate_limited"
    http_status = 429
    message = "Rate limit exceeded"

    def __init__(self, scope: str, retry_after: timedelta, **kwargs: Any) -> None:
        """Округляет `retry_after` вверх до целых секунд (не меньше 1) и ставит заголовок."""
        seconds = max(1, math.ceil(retry_after.total_seconds()))
        super().__init__(
            headers={"Retry-After": str(seconds)},
            details={"scope": scope, "retry_after_seconds": seconds},
            **kwargs,
        )

    @classmethod
    def from_result(cls, result: RateLimitResult, scope: str) -> RateLimitedError:
        """Ошибка по результату ограничителя `ModuleRedis.rate_limiter.hit`."""
        return cls(scope=scope, retry_after=result.retry_after)


class InternalError(DomainError):
    """Необработанная ошибка; `details` пусты вне `DEBUG_MODE`."""

    code = "core.internal"
    http_status = 500
    message = "Internal server error"


class ServiceUnavailableError(DomainError):
    """Зависимость недоступна при политике fail-closed (ADR-003); заголовок `Retry-After`."""

    code = "core.service_unavailable"
    http_status = 503
    message = "Service temporarily unavailable"

    def __init__(self, retry_after_seconds: int = 30, **kwargs: Any) -> None:
        """Ставит заголовок `Retry-After` (по умолчанию 30 с, ADR-003)."""
        super().__init__(headers={"Retry-After": str(retry_after_seconds)}, **kwargs)


# Ошибки shared kernel по кодам (SYS-03-R8, таблица кодов `core.*`).
CORE_ERRORS: tuple[type[DomainError], ...] = (
    BadRequestError,
    InvalidCursorError,
    UnauthenticatedError,
    ForbiddenError,
    NotFoundError,
    MethodNotAllowedError,
    VersionConflictError,
    RequestInProgressError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
    IdempotencyKeyReusedError,
    RateLimitedError,
    InternalError,
    ServiceUnavailableError,
)

# HTTP-статус → ошибка shared kernel для `HTTPException` фреймворка (404 маршрута, 405 и т.п.);
# остальные статусы получают `core.bad_request` (4xx) или `core.internal` (5xx).
CORE_ERROR_BY_STATUS: Mapping[int, type[DomainError]] = MappingProxyType(
    {
        400: BadRequestError,
        401: UnauthenticatedError,
        403: ForbiddenError,
        404: NotFoundError,
        405: MethodNotAllowedError,
        413: PayloadTooLargeError,
        415: UnsupportedMediaTypeError,
        422: ValidationFailedError,
        500: InternalError,
        503: ServiceUnavailableError,
    }
)
