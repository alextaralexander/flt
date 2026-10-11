"""Обработчики исключений HTTP-слоя: единый конверт `ErrorResponseV1` (SYS-03-R7–R9, R17–R19, R22).

Все ответы 4xx и 5xx монолита строятся функцией `error_envelope()`: доменные ошибки
(`DomainError` и наследники модулей), конфликт версии (`StaleDataError` → `409
core.version_conflict`), валидация (`422 core.validation_failed`), `HTTPException` фреймворка
(404 маршрута, 405), недоступный Redis при политике fail-closed (`503
core.service_unavailable`) и необработанные ошибки (`500 core.internal`, `app/core/http/logging_middleware.py`).
Детали из `hidden_details` и параметры старых исключений, раскрывающие лишнее, скрываются
вне `DEBUG_MODE`.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.dao.caching import RedisUnavailableError
from app.core.exceptions import (
    BaseCustomException,
    InsufficientPermissionsError,
    InvalidTokenError,
    ModelNotFoundInDatabaseError,
)
from app.core.http.context import current_request_id
from app.core.http.errors import (
    CORE_ERROR_BY_STATUS,
    BadRequestError,
    DomainError,
    ForbiddenError,
    InternalError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthenticatedError,
    ValidationFailedError,
    VersionConflictError,
)
from app.core.http.idempotency import IdempotentReplayError
from app.core.http.schemas import ErrorMessage, ErrorMessages, ErrorResponseV1
from app.core.ids import new_id
from configs.settings import settings


def error_envelope(
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Ответ в конверте `ErrorResponseV1` с `request_id` текущего запроса (SYS-03-R7, R20).

    Args:
        status_code: HTTP-статус.
        code: код ошибки `<module>.<error_name>`.
        message: текст для разработчика на английском.
        details: детали ошибки.
        headers: дополнительные заголовки (`Retry-After`, `WWW-Authenticate`).
    """
    content = ErrorResponseV1(
        messages=ErrorMessages(
            ERROR=[ErrorMessage(code=code, message=message, details=jsonable_encoder(dict(details or {})))]
        ),
        # Вне RequestContextMiddleware (прямой вызов в тестах) ID генерируется здесь (SYS-03-R20).
        request_id=current_request_id() or str(new_id()),
    )
    return JSONResponse(status_code=status_code, content=content.model_dump(mode="json"), headers=headers)


def domain_error_response(exc: DomainError) -> JSONResponse:
    """Конверт для доменной ошибки; `hidden_details` скрываются вне `DEBUG_MODE`."""
    details = dict(exc.details)
    if not settings.DEBUG_MODE:
        for name in type(exc).hidden_details:
            details.pop(name, None)
        if exc.status >= 500:
            details = {}
    return error_envelope(exc.status, exc.error_code, exc.error_message, details, exc.headers)


def _validation_errors(errors: Any) -> list[dict[str, Any]]:
    """Ошибки валидации в форме `{loc, type, msg, ctx}` (SYS-03-R9); `input` не возвращается."""
    return [
        {
            "loc": list(error.get("loc", ())),
            "type": error.get("type", "value_error"),
            "msg": error.get("msg", ""),
            "ctx": jsonable_encoder(error.get("ctx", {}), custom_encoder={Exception: str}),
        }
        for error in errors
    ]


def _legacy_error(exc: BaseCustomException) -> DomainError:
    """Ошибки boilerplate (до перевода модулей на `DomainError`) — в коды `core.*`."""
    if isinstance(exc, ModelNotFoundInDatabaseError):
        return NotFoundError()
    if isinstance(exc, InsufficientPermissionsError):
        return ForbiddenError(details=exc.parameters)
    if isinstance(exc, InvalidTokenError):
        return UnauthenticatedError()
    return InternalError(details={"legacy_code": exc.message_mnemo_code})


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрирует обработчики исключений приложения (единственная точка, SYS-03-R7)."""

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        """Доменная ошибка модуля или shared kernel."""
        return domain_error_response(exc)

    @app.exception_handler(BaseCustomException)
    async def legacy_error_handler(request: Request, exc: BaseCustomException) -> JSONResponse:
        """Ошибки boilerplate: 404 без `is_deleted`, 403 без недостающих прав, 401 с `WWW-Authenticate`."""
        return domain_error_response(_legacy_error(exc))

    @app.exception_handler(StaleDataError)
    async def stale_data_handler(request: Request, exc: StaleDataError) -> JSONResponse:
        """Конфликт оптимистической блокировки ORM — `409 core.version_conflict` (SYS-05-R18)."""
        return domain_error_response(VersionConflictError())

    @app.exception_handler(RedisUnavailableError)
    async def redis_unavailable_handler(request: Request, exc: RedisUnavailableError) -> JSONResponse:
        """Redis недоступен там, где политика fail-closed (ADR-003) — `503` с `Retry-After: 30`."""
        return domain_error_response(ServiceUnavailableError())

    @app.exception_handler(IdempotentReplayError)
    async def idempotent_replay_handler(request: Request, exc: IdempotentReplayError) -> Response:
        """Повтор запроса с тем же `Idempotency-Key` — сохранённый ответ (SYS-03-R18)."""
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Ошибки валидации запроса — `422 core.validation_failed` с `details.errors`."""
        return domain_error_response(ValidationFailedError(details={"errors": _validation_errors(exc.errors())}))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """`HTTPException` фреймворка (404 маршрута, 405) — в коды `core.*` по статусу."""
        error_class = CORE_ERROR_BY_STATUS.get(exc.status_code)
        if error_class is None:
            error_class = InternalError if exc.status_code >= 500 else BadRequestError
        error = error_class()
        error.status = exc.status_code
        error.headers.update(exc.headers or {})
        return domain_error_response(error)
