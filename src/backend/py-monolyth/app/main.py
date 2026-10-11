"""Сборка приложений монолита по реестру модулей и роли запуска (ADR-002, ADR-004 раздел 3.5).

- `create_app()` — HTTP-приложение роли `api`: REST модулей (`/api/v1/<module>`), служебные
  `/v1/health`, `/v1/ready`, `/v1/metrics`, документация `/api/docs`, `/api/openapi.json`;
  каждый ответ несёт `X-Instance-Id` (SYS-05-R5), `X-Request-ID` и `Content-Language` (SYS-03-R20, R30);
  Kafka не подключает. В роли `all` (local, pytest) дополнительно поднимает в своём
  lifespan брокер Kafka роли `worker`.
- `create_worker_app()` — `AsgiFastStream` роли `worker`: брокер Kafka с роутерами модулей
  и служебный HTTP (`/v1/health`, `/v1/ready`, `/v1/metrics`, `/asyncapi/kafka`).

Фабрики не мутируют глобальное состояние: тесты создают собственные экземпляры.
Внешние ресурсы (телеметрия, пул БД, Redis, брокер) создаются и освобождаются
симметрично в lifespan. Процесс по роли запускает `python -m app` (`app/__main__.py`).
"""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.asgi import AsgiFastStream
from opentelemetry.sdk.trace import TracerProvider
from starlette.middleware.cors import CORSMiddleware

from app.core.container import container
from app.core.dao.caching import ModuleRedis
from app.core.dao.caching.redis_conn import close_redis_client
from app.core.dao.db_helpers.db_connection import dispose_engine, get_engine, get_session_maker
from app.core.http.body_limit import BodyLimitMiddleware
from app.core.http.context import RequestContextMiddleware
from app.core.http.deprecation import DeprecationMiddleware
from app.core.http.exception_handlers import register_exception_handlers
from app.core.http.idempotency import IdempotencyMiddleware
from app.core.http.instance_header import InstanceIdMiddleware
from app.core.http.logging_middleware import register_logging_middleware
from app.core.kafka.broker import create_broker
from app.core.kafka.relay import BrokerSink, OutboxRelay, OutboxSink
from app.core.kafka.scheduler import Scheduler
from app.core.logging import logger_settings
from app.core.metrics.metrics_controller import router as service_router
from app.core.metrics.metrics_middleware import PrometheusMiddleware
from app.core.modules import ModuleDefinition, install_modules, load_modules, module_routers
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
# Страница OAuth2-redirect Swagger UI — тоже под /api (по умолчанию FastAPI ставит /docs/oauth2-redirect).
DOCS_OAUTH2_REDIRECT_URL = f"{DOCS_URL}/oauth2-redirect"


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
    """Модули для сборки: переданные явно (тесты) или загруженные из реестра.

    Модули реестра проверяются при старте и регистрируются в контейнере процесса (`install_modules`:
    точки расширения, провайдер ролей, верификатор токенов); явно переданные модули тестов контейнер
    процесса не трогают.
    """
    if modules is not None:
        return modules
    registry = load_modules(MODULES)
    install_modules(registry)
    return registry


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
        swagger_ui_oauth2_redirect_url=DOCS_OAUTH2_REDIRECT_URL,
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
    # Заголовки вывода операций из эксплуатации (SYS-03-R28).
    application.add_middleware(DeprecationMiddleware)
    # Сохранение ответов идемпотентных POST (SYS-03-R18): внутри logging-middleware,
    # чтобы видеть ответы обработчиков исключений и необработанные ошибки.
    application.add_middleware(IdempotencyMiddleware)

    application.include_router(service_router)
    for router in module_routers(resolved_modules):
        application.include_router(router)

    register_exception_handlers(application)

    # Logging middleware (access-лог + 500 для неперехваченных ошибок)
    register_logging_middleware(application)
    # X-Request-ID и Content-Language — снаружи logging-middleware: ID есть и в 500 (SYS-03-R20, R30)
    application.add_middleware(RequestContextMiddleware)
    # Лимит тела — до чтения тела любым слоем (SYS-03-R26); 413 получает X-Request-ID и X-Instance-Id.
    application.add_middleware(BodyLimitMiddleware)
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

    resolved = _resolve_modules(modules)
    broker = create_broker(resolved, role=role)
    service_app = create_service_app()
    # Приёмник DLQ консьюмеров и relay outbox — брокер процесса (SYS-04-R24, R27).
    container.register(OutboxSink, lambda: BrokerSink(broker), replace=True)
    relay_tasks: list[asyncio.Task[None]] = []
    relay_stop = asyncio.Event()

    async def start_relays() -> None:
        """Relay outbox для каждого модуля с outbox и планировщик задач — после подключения брокера."""
        relay_stop.clear()
        if any(module.schedules for module in resolved):
            scheduler = Scheduler(resolved, ModuleRedis("shared_kernel"), get_session_maker())
            relay_tasks.append(asyncio.create_task(scheduler.run(relay_stop), name="scheduler"))
        for module in resolved:
            if module.outbox is None:
                continue
            relay = OutboxRelay(
                module.name, module.outbox, get_session_maker(), BrokerSink(broker), ModuleRedis("shared_kernel")
            )
            relay_tasks.append(asyncio.create_task(relay.run(relay_stop), name=f"outbox-relay-{module.name}"))

    async def stop_relays() -> None:
        """Остановка relay до отключения брокера; незавершённые проходы откатываются транзакцией."""
        relay_stop.set()
        await asyncio.gather(*relay_tasks, return_exceptions=True)
        relay_tasks.clear()

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
        after_startup=[start_relays],
        on_shutdown=[stop_relays],
        after_shutdown=[after_shutdown] if manage_resources else [],
    )
