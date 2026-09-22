"""HTTP-middleware: структурный access-лог и 500-ответ для неперехваченных ошибок."""

import time
import traceback
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request, Response
from py_main_lib.services.schemas.v1_schemas import ErrorResponseV1, MessagesV1
from starlette.responses import JSONResponse
from uvicorn.protocols.utils import get_path_with_query_string

from app.core.schemas import ErrorMessageSchema, InternalServerErrorMessageSchema
from configs.settings import settings


# Служебные пути опрашиваются probe-ами и Prometheus каждые 15-30 секунд —
# в access-логе они только шумят (в метрики при этом попадают).
EXCLUDED_ACCESS_LOG_PATHS = frozenset({"/v1/health", "/v1/ready", "/v1/metrics"})


def _build_internal_error_response(exception_info: Exception) -> JSONResponse:
    """500 в едином конверте `ErrorResponseV1`; traceback — только в DEBUG_MODE."""
    if settings.DEBUG_MODE:
        error_message: Any = InternalServerErrorMessageSchema(
            log_message=str(exception_info).splitlines(),
            traceback=traceback.format_exception(type(exception_info), exception_info, exception_info.__traceback__),
        )
    else:
        error_message = ErrorMessageSchema(message_mnemo_code="INTERNAL_SERVER_ERROR", parameters={})

    error_response_content = ErrorResponseV1(messages=MessagesV1(ERROR=[error_message])).model_dump()
    return JSONResponse(status_code=500, content=error_response_content)


def register_logging_middleware(app: FastAPI) -> None:
    """Регистрирует middleware для FastAPI приложения."""

    @app.middleware("http")
    async def logging_middleware(request: Request, call_next: Any) -> Response:
        """Middleware для логирования HTTP-запросов и обработки неожиданных ошибок."""
        structlog.contextvars.clear_contextvars()
        api_logger = structlog.stdlib.get_logger("api")
        start_time = time.perf_counter_ns()

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            structlog.stdlib.get_logger("api.error").exception("Uncaught exception")
            response = _build_internal_error_response(exc)

        process_time = time.perf_counter_ns() - start_time
        url = get_path_with_query_string(cast("Any", request.scope))
        client_host = request.client.host if request.client else None
        client_port = request.client.port if request.client else None
        http_method = request.method

        if request.url.path not in EXCLUDED_ACCESS_LOG_PATHS:
            api_logger.info(
                f'{response.status_code} {http_method} "{url}"',
                http={"method": http_method, "url": url, "status_code": response.status_code},
                network={"client": {"ip": client_host, "port": client_port}},
                duration=process_time / 10**9,
            )
        response.headers["X-Process-Time"] = str(process_time / 10**9)

        return response
