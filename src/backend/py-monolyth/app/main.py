"""Точка сборки FastAPI-приложения.

Приложение собирает фабрика `create_app()`: тесты создают собственный
экземпляр и не мутируют приложение продового процесса. Внешние ресурсы
(телеметрия, пул БД, Redis) создаются и освобождаются симметрично в
`lifespan`. Запуск — `make dev` (uvicorn) или `uvi_run.py` (Docker).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.controllers import v1_router
from app.api.exception_handlers import register_exception_handlers
from app.brokers.kafka import publishers as kafka_publishers  # noqa: F401
from app.brokers.kafka import subscribers as kafka_subscribers  # noqa: F401
from app.brokers.kafka.kafka_router import kafka_router
from app.core.dao.caching.redis_conn import close_redis_client
from app.core.dao.db_helpers.db_connection import dispose_engine, get_engine
from app.core.logging import logger_settings
from app.core.metrics.metrics_middleware import PrometheusMiddleware
from app.core.middlewares.logging_middleware import register_logging_middleware
from app.core.security.auth_service import reset_auth_service
from app.core.telemetry import SERVICE_NAME, setup_telemetry, stop_telemetry
from configs.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Жизненный цикл ресурсов: startup — создание, shutdown — освобождение."""
    tracer_provider = setup_telemetry(SERVICE_NAME, settings.OTLP_EXPORTER_ENDPOINT)
    app.state.tracer_provider = tracer_provider
    app.state.db_engine = get_engine()

    yield

    await close_redis_client()
    reset_auth_service()
    await dispose_engine()
    stop_telemetry(tracer_provider)


def create_app() -> FastAPI:
    """Собирает приложение: middleware, роутеры, exception handler-ы, логирование."""
    logger_settings.setup_logging()

    application = FastAPI(root_path=settings.ROOT_PATH, lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOW_ORIGINS,
        allow_credentials=settings.ALLOW_CREDENTIALS,
        allow_methods=settings.ALLOW_METHODS,
        allow_headers=settings.ALLOW_HEADERS,
    )
    application.add_middleware(PrometheusMiddleware)

    # API Routers
    application.include_router(v1_router)

    # Broker Routes
    application.include_router(kafka_router)

    # Exception Handlers
    register_exception_handlers(application)

    # Logging middleware (внешний слой: access-лог + 500 для неперехваченных ошибок)
    register_logging_middleware(application)

    return application


app = create_app()
