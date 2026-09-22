"""Главные Fixture для тестов."""

import asyncio
import sys
from asyncio import AbstractEventLoop
from typing import Any, AsyncGenerator, Iterator, List

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import StrictRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from py_main_lib.security.auth_service import get_auth_service
from py_main_lib.security.schemas import UserSecuritySchema
from py_main_lib.tests.settings import settings


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def db_migrate() -> Iterator[None]:
    """Применение и откат миграций в тестовой базе данных.

    - Выполняет `alembic upgrade head`, чтобы применить все миграции перед тестами.
    - После завершения тестов откатывает миграции с помощью `alembic downgrade base`.
    - Используется на уровне сессии (`scope="session"`), чтобы миграции выполнялись один раз за тестовую сессию.
    """
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    yield
    command.downgrade(alembic_cfg, "base")


# @pytest.fixture(scope="session")
# async def engine(db_migrate: None):
#     engine = create_async_engine(
#         url=settings.sqlalchemy_database_uri,  # asyncpg ок
#         poolclass=NullPool,                    # не реиспользуем коннекты между тестами
#         future=True,
#     )
#     try:
#         yield engine
#     finally:
#         await engine.dispose()


@pytest_asyncio.fixture
async def overridden_get_session(db_migrate: None) -> AsyncGenerator[AsyncSession, None]:
    """Создание асинхронной сессии базы данных, которая переопределяет стандартную сессию.

    Гарантирует, что тесты будут использовать новую сессию, а не боевую базу данных.
    """
    engine = create_async_engine(url=settings.sqlalchemy_database_uri)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session_maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_conn() -> AsyncGenerator[StrictRedis, None]:
    """Асинхронный генератор соединения Redis."""
    redis_client = StrictRedis(host="localhost", port=6379, decode_responses=True)
    yield redis_client


@pytest_asyncio.fixture
async def test_user(redis_conn: StrictRedis) -> UserSecuritySchema:
    """Схема UserSecuritySchema для тестов."""
    auth_service = await get_auth_service("local", redis_conn)
    decoded_token = await auth_service.verify_token(settings.TEST_AUTH_TOKEN)
    user_id = decoded_token["USER_ID"]
    all_permissions = await auth_service.get_all_user_permissions(user_id)
    user = UserSecuritySchema(user_id=user_id, permissions=all_permissions, access_token=settings.TEST_AUTH_TOKEN)
    return user


@pytest.fixture
async def client(overridden_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Клиент, что будет посылать запросы на наш API."""
    async with AsyncClient(
        transport=ASGITransport(app=overridden_app),
        base_url="http://test/",
        headers={"Authorization": f"Bearer {settings.TEST_AUTH_TOKEN}"},
        timeout=1,
    ) as async_client:
        yield async_client


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: List[pytest.Function]) -> None:
    """Без этого просто не работает. Скопировано с интернета:

    We can't use auto use, because it appends fixture to the end
    but session from db_session fixture must be closed before migrations downgrade
    """
    for item in items:
        item.fixturenames = ["overridden_get_session"] + item.fixturenames  # noqa


@pytest.fixture(scope="session")
def event_loop(request: Any) -> Iterator[AbstractEventLoop]:
    """Без этого просто не работает. Скопировано с интернета.

    Create an instance of the default event loop for each test case.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


async def mocked_function() -> None:
    """Функция для overriding и вызова в тестовом endpoint."""
