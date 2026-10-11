"""Подключение к базе данных.

Engine и фабрика сессий создаются лениво при первом обращении, а не при
импорте модуля: инструменты (Alembic, скрипты, тесты) могут импортировать
код приложения без побочных эффектов. Владение жизненным циклом — у
`lifespan` в `app.main`: там engine прогревается на старте и освобождается
через `dispose_engine()` на остановке.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from configs.settings import settings


_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Engine приложения (создаётся при первом вызове)."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            url=settings.sqlalchemy_database_uri,
            pool_recycle=settings.POOL_RECYCLE,  # Время жизни соединения, сек
            pool_timeout=settings.POOL_TIMEOUT,  # Максимальное ожидание соединения из пула, сек
            pool_size=settings.POOL_SIZE,  # Размер пула соединений
            max_overflow=settings.POOL_MAX_OVERFLOW,  # Допустимое превышение pool_size
            pool_pre_ping=settings.POOL_PRE_PING,  # Проверять соединение перед использованием
        )
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
