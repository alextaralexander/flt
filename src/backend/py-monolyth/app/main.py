"""Сборка приложений монолита по реестру модулей и роли запуска (ADR-002, ADR-004 раздел 3.5).

- `create_app()` — HTTP-приложение роли `api`: REST модулей (`/api/v1/<module>`), служебные
  `/v1/health`, `/v1/ready`, `/v1/metrics`, документация `/api/docs`, `/api/openapi.json`;
  каждый ответ несёт `X-Instance-Id` (SYS-05-R5);
  Kafka не подключает. В роли `all` (local, pytest) дополнительно поднимает в своём
  lifespan брокер Kafka роли `worker`.
- `create_worker_app()` — `AsgiFastStream` роли `worker`: брокер Kafka с роутерами модулей
  и служебный HTTP (`/v1/health`, `/v1/ready`, `/v1/metrics`, `/asyncapi/kafka`).

Фабрики не мутируют глобальное состояние: тесты создают собственные экземпляры.
Внешние ресурсы (телеметрия, пул БД, Redis, брокер) создаются и освобождаются
симметрично в lifespan. Процесс по роли запускает `python -m app` (`app/__main__.py`).
"""

from collections.abc import AsyncGenerator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.asgi import AsgiFastStream
from opentelemetry.sdk.trace import TracerProvider
from starlette.middleware.cors import CORSMiddleware

from app.core.dao.caching.redis_conn import close_redis_client
from app.core.dao.db_helpers.db_connection import dispose_engine, get_engine
from app.core.http.exception_handlers import register_exception_handlers
from app.core.http.instance_header import InstanceIdMiddleware
from app.core.http.logging_middleware import register_logging_middleware
from app.core.kafka.broker import create_broker
from app.core.logging import logger_settings
from app.core.metrics.metrics_controller import router as service_router
from app.core.metrics.metrics_middleware import PrometheusMiddleware
from app.core.modules import ModuleDefinition, load_modules, module_routers
from app.core.telemetry import SERVICE_NAME, setup_telemetry, stop_telemetry
from app.modules.registry import MODULES
from configs.settings import AppRole, settings


# Служебные пути роли `worker`: обслуживаются тем же роутером, что и в роли `api`.
WORKER_SERVICE_PATHS = ("/v1/health", "/v1/ready", "/v1/metrics")
ASYNCAPI_PATH = "/asyncapi/kafka"
# Документация REST — под /api (снаружи её закрывает HAProxy, ADR-012).
OPENAPI_URL = "/api/openapi.json"
DOCS_URL = "/api/docs"
REDOC_URL = "/api/redoc"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Жизненный цикл ресурсов HTTP-приложения: startup — создание, shutdown — освобождение.

    В роли `all` после общих ресурсов поднимается брокер Kafka приложения воркера
    (`app.state.worker`) и останавливается первым.
    """
    tracer_provider = setup_telemetry(SERVICE_NAME, settings.OTLP_EXPORTER_ENDPOINT)
    app.state.tracer_provider = tracer_provider
    app.state.db_engine = get_engine()

    async with AsyncExitStack() as stack:
        worker: AsgiFastStream | None = getattr(app.state, "worker", None)
        if worker is not None:
            await stack.enter_async_context(worker.start_lifespan_context())
        yield

    await close_redis_client()
    await dispose_engine()
    stop_telemetry(tracer_provider)


def _resolve_modules(modules: Sequence[ModuleDefinition] | None) -> Sequence[ModuleDefinition]:
    """Модули для сборки: переданные явно (тесты) или загруженные из реестра."""
    return load_modules(MODULES) if modules is None else modules


def create_app(modules: Sequence[ModuleDefinition] | None = None, role: AppRole | None = None) -> FastAPI:
    """Собирает HTTP-приложение: middleware, служебный роутер, роутеры модулей, обработчики ошибок.

    Args:
        modules: Модули для подключения; по умолчанию — реестр `app.modules.registry.MODULES`.
        role: Роль процесса (`api` или `all`); по умолчанию — `APP_ROLE` из настроек.

    Returns:
        Приложение FastAPI; Kafka подключается только в роли `all` (ADR-004).
    """
    logger_settings.setup_logging()
    resolved_modules = _resolve_modules(modules)
    resolved_role = role or settings.role

    application = FastAPI(
        lifespan=lifespan,
        openapi_url=OPENAPI_URL,
        docs_url=DOCS_URL,
        redoc_url=REDOC_URL,
    )
    if resolved_role is AppRole.ALL:
        application.state.worker = create_worker_app(resolved_modules, manage_resources=False, role=resolved_role)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOW_ORIGINS,
        allow_credentials=settings.ALLOW_CREDENTIALS,
        allow_methods=settings.ALLOW_METHODS,
        allow_headers=settings.ALLOW_HEADERS,
    )
    application.add_middleware(PrometheusMiddleware)

    application.include_router(service_router)
    for router in module_routers(resolved_modules):
        application.include_router(router)

    register_exception_handlers(application)

    # Logging middleware (access-лог + 500 для неперехваченных ошибок)
    register_logging_middleware(application)
    # Внешний слой: X-Instance-Id в каждом ответе, включая 500 и handshake WebSocket (SYS-05-R5)
    application.add_middleware(InstanceIdMiddleware)

    return application


def create_service_app() -> FastAPI:
    """Служебное HTTP-приложение роли `worker`: только `/v1/health`, `/v1/ready`, `/v1/metrics`."""
    service_app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    service_app.include_router(service_router)
    return service_app


def create_worker_app(
    modules: Sequence[ModuleDefinition] | None = None,
    manage_resources: bool = True,
    role: AppRole = AppRole.WORKER,
) -> AsgiFastStream:
    """Собирает приложение роли `worker`: брокер Kafka с роутерами модулей и служебный HTTP.

    Args:
        modules: Модули для подключения; по умолчанию — реестр `app.modules.registry.MODULES`.
        manage_resources: Создавать и освобождать телеметрию, пул БД и Redis в хуках приложения;
            False — ресурсами владеет внешний lifespan (роль `all`).
        role: Роль процесса для client_id Kafka.

    Returns:
        ASGI-приложение FastStream; брокер подключается к Kafka в его lifespan.
    """
    logger_settings.setup_logging()

    broker = create_broker(_resolve_modules(modules), role=role)
    service_app = create_service_app()
    # Провайдер трейсов живёт столько же, сколько приложение (заполняется в on_startup).
    tracer_providers: list[TracerProvider] = []

    async def on_startup() -> None:
        """Телеметрия и пул БД — до подключения брокера."""
        tracer_providers.append(setup_telemetry(SERVICE_NAME, settings.OTLP_EXPORTER_ENDPOINT))
        get_engine()

    async def after_shutdown() -> None:
        """Освобождение ресурсов после остановки брокера."""
        await close_redis_client()
        await dispose_engine()
        while tracer_providers:
            stop_telemetry(tracer_providers.pop())

    return AsgiFastStream(
        broker,
        asgi_routes=[(path, service_app) for path in WORKER_SERVICE_PATHS],
        asyncapi_path=ASYNCAPI_PATH,
        on_startup=[on_startup] if manage_resources else [],
        after_shutdown=[after_shutdown] if manage_resources else [],
    )
