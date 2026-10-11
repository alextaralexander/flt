"""Подключение к базе данных: engine с параметрами по роли запуска (ADR-003, SYS-05).

Engine и фабрика сессий создаются лениво при первом обращении, а не при импорте
модуля: инструменты (Alembic, скрипты, тесты) могут импортировать код приложения
без побочных эффектов. Владение жизненным циклом — у lifespan приложения роли:
engine создаётся на старте и освобождается через `dispose_engine()` на остановке.
Пул — один на процесс, его размер зависит от роли (`api` держит HTTP-нагрузку,
`worker` — консьюмеры), чтобы сумма соединений всех инстансов укладывалась в
`max_connections` PostgreSQL.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from configs.settings import AppRole, settings
from configs.stands import instance_id


@dataclass(frozen=True)
class RolePoolConfig:
    """Параметры пула и таймаут запросов для роли запуска."""

    pool_size: int
    max_overflow: int
    statement_timeout: str


# ADR-003, раздел 2.2 A и правило 2; SYS-05: размер пула и statement_timeout по ролям.
POOL_BY_ROLE: dict[AppRole, RolePoolConfig] = {
    AppRole.API: RolePoolConfig(pool_size=10, max_overflow=10, statement_timeout="30s"),
    AppRole.ALL: RolePoolConfig(pool_size=10, max_overflow=10, statement_timeout="30s"),
    AppRole.WORKER: RolePoolConfig(pool_size=5, max_overflow=5, statement_timeout="10min"),
    AppRole.MEDIA_AGENT: RolePoolConfig(pool_size=5, max_overflow=5, statement_timeout="10min"),
    AppRole.MIGRATE: RolePoolConfig(pool_size=1, max_overflow=0, statement_timeout="10min"),
}
POOL_PRE_PING = True
POOL_RECYCLE_SECONDS = 1800
POOL_TIMEOUT_SECONDS = 10
IDLE_IN_TRANSACTION_SESSION_TIMEOUT = "60s"
# PostgreSQL обрезает application_name до 63 байт.
APPLICATION_NAME_MAX_LENGTH = 63

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def engine_options(role: AppRole) -> dict[str, Any]:
    """Параметры `create_async_engine` для роли запуска.

    Args:
        role: Роль процесса (ADR-004).

    Returns:
        Размер пула, проверки соединений и серверные параметры сессии
        (`search_path=public`, `timezone=UTC`, `application_name=flt-<role>-<instance_id>`,
        `statement_timeout` по роли, `idle_in_transaction_session_timeout`).
    """
    pool = POOL_BY_ROLE[role]
    application_name = f"flt-{role}-{instance_id()}"[:APPLICATION_NAME_MAX_LENGTH]
    return {
        "pool_size": pool.pool_size,
        "max_overflow": pool.max_overflow,
        "pool_pre_ping": POOL_PRE_PING,
        "pool_recycle": POOL_RECYCLE_SECONDS,
        "pool_timeout": POOL_TIMEOUT_SECONDS,
        "connect_args": {
            "server_settings": {
                "search_path": "public",
                "timezone": "UTC",
                "application_name": application_name,
                "statement_timeout": pool.statement_timeout,
                "idle_in_transaction_session_timeout": IDLE_IN_TRANSACTION_SESSION_TIMEOUT,
            },
        },
    }


def get_engine() -> AsyncEngine:
    """Engine процесса (создаётся при первом вызове с параметрами роли из настроек)."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(url=settings.sqlalchemy_database_uri, **engine_options(settings.role))
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Фабрика асинхронных сессий (создаётся при первом вызове)."""
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_maker


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI-зависимость: сессия БД на время запроса."""
    async with get_session_maker()() as session:
        yield session


async def dispose_engine() -> None:
    """Закрыть пул соединений (вызывается из lifespan при shutdown)."""
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_maker = None
