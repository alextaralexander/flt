"""Обработчики исключений HTTP-слоя.

Все ошибки — доменные, валидационные (422) и `HTTPException` — отдаются
в едином конверте `ErrorResponseV1`: клиент всегда парсит один формат
(см. также 500-ответ в `app/core/http/logging_middleware.py`).
Чувствительные параметры скрываются от клиента вне DEBUG_MODE.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from py_main_lib.services.schemas.v1_schemas import ErrorResponseV1, MessagesV1
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.exceptions import (
    BaseCustomException,
    InsufficientPermissionsError,
    InvalidTokenError,
    ModelNotFoundInDatabaseError,
)
from app.core.schemas import ErrorMessageSchema
from configs.settings import settings


def error_envelope(
    status_code: int,
    message_mnemo_code: str,
    parameters: dict[str, Any],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Единый конверт ошибки `ErrorResponseV1` — общий для всех хендлеров."""
    error_message = ErrorMessageSchema(message_mnemo_code=message_mnemo_code, parameters=parameters)
    content = ErrorResponseV1(messages=MessagesV1(ERROR=[error_message]))
    return JSONResponse(status_code=status_code, content=content.model_dump(), headers=headers)


def _error_response(
    exc: BaseCustomException,
    status_code: int,
    hide_parameters: tuple[str, ...] = (),
) -> JSONResponse:
    """Конверт для доменной ошибки; `hide_parameters` скрываются вне DEBUG_MODE."""
    parameters: dict[str, Any] = dict(exc.parameters)
    if not settings.DEBUG_MODE:
        for parameter in hide_parameters:
            parameters.pop(parameter, None)

    return error_envelope(status_code, exc.message_mnemo_code, parameters)


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрирует exception handler-ы в FastAPI."""

    @app.exception_handler(ModelNotFoundInDatabaseError)
    async def model_not_found_in_database_error_handler(
        request: Request, exc: ModelNotFoundInDatabaseError
    ) -> JSONResponse:
        """404: не сообщаем клиенту, существует ли объект в БД (`is_deleted`)."""
        return _error_response(exc, status_code=404, hide_parameters=("is_deleted",))

    @app.exception_handler(InsufficientPermissionsError)
    async def insufficient_permission_error_handler(
        request: Request, exc: InsufficientPermissionsError
    ) -> JSONResponse:
        """403: не сообщаем клиенту, каких прав ему не хватает."""
        return _error_response(exc, status_code=403, hide_parameters=("missing_permissions",))

    @app.exception_handler(InvalidTokenError)
    async def invalid_token_error_handler(request: Request, exc: InvalidTokenError) -> JSONResponse:
        """401: невалидный токен авторизации."""
        return _error_response(exc, status_code=401)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """422: ошибки валидации запроса — в том же конверте, что и доменные ошибки."""
        return error_envelope(
            status_code=422,
            message_mnemo_code="REQUEST_VALIDATION_ERROR",
            parameters={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """`HTTPException` (в т.ч. 404 несуществующего маршрута) — в едином конверте."""
        return error_envelope(
            status_code=exc.status_code,
            message_mnemo_code="HTTP_ERROR",
            parameters={"detail": exc.detail},
            headers=exc.headers,
        )
