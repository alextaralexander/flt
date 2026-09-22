"""Главные fixture для тестов.

Аутентификация:
- HTTP-тесты переопределяют одну зависимость — `get_current_user` —
  через `dependency_overrides` (fixture `overridden_app`);
- брокерные no_db-тесты подменяют `check_token` (FastStream
  резолвит зависимости своим механизмом, overrides FastAPI туда не достают).

БД: тесты интеграционные, ходят в Postgres тестового стенда;
миграции накатываются один раз на сессию и откатываются в конце.
"""

from collections.abc import AsyncGenerator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.dao.db_helpers.db_connection import get_session
from app.core.security import security
from app.core.security.permissions import MyEntityPermissions
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import get_current_user
from app.core.telemetry import SERVICE_NAME, setup_telemetry
from app.main import create_app
from configs.settings import settings
from tests.fixtures.my_entity_fixture import created_my_entity  # noqa: F401
from tests.settings import test_settings


# В приложении провайдер настраивает lifespan; тесты (Test*Broker) работают без него,
# а broker-middleware ожидает настроенную трассировку — настраиваем без экспортера.
setup_telemetry(SERVICE_NAME, endpoint="")

# Тестовый экземпляр приложения: фабрика позволяет тестам регистрировать
# свои endpoint-ы и dependency_overrides, не мутируя приложение продового процесса.
app = create_app()

# Отдельный engine для тестов: не зависит от ленивых глобалов приложения.
engine = create_async_engine(url=settings.sqlalchemy_database_uri)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def mocked_function() -> None:
    """Зависимость-заглушка: тесты подменяют её, чтобы вызвать нужное поведение."""


@app.get("/mocked_endpoint")
async def mocked_endpoint(fn: Any = Depends(mocked_function)) -> None:
    """Тестовый endpoint (регистрируется один раз при импорте conftest)."""
    await fn()


@pytest.fixture(scope="session")
def db_migrate() -> Iterator[None]:
    """Применение и откат миграций в тестовой базе данных.

    - Выполняет `alembic upgrade head`, чтобы применить все миграции перед тестами.
    - После завершения тестов откатывает миграции с помощью `alembic downgrade base`.
    - Используется на уровне сессии (`scope="session"`), чтобы миграции выполнялись один раз за тестовую сессию.
    """
    # Защита от запуска на реальной БД: TEST_MODE задаёт только envs/test/test.env.
    assert test_settings.TEST_MODE, "TEST_MODE не установлен — тесты запущены не на тестовом стенде."

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    yield
    command.downgrade(alembic_cfg, "base")


@pytest_asyncio.fixture
async def overridden_get_session(db_migrate: None) -> AsyncGenerator[AsyncSession, None]:
    """Сессия тестовой БД, которой подменяется штатная `get_session`."""
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def test_user() -> UserSecuritySchema:
    """Аутентифицированный пользователь со всеми permissions примера."""
    return UserSecuritySchema(
        user_id=test_settings.TEST_USER_ID,
        permissions=_all_test_permissions(),
        access_token=test_settings.TEST_AUTH_TOKEN,
    )


@pytest_asyncio.fixture
async def overridden_app(
    overridden_get_session: AsyncSession,
    test_user: UserSecuritySchema,
) -> AsyncGenerator[FastAPI, Any]:
    """Приложение с переопределёнными зависимостями БД и аутентификации.

    - `get_session` → сессия тестовой БД;
    - `get_current_user` → `test_user` (проверка permissions при этом
      выполняется по-настоящему — RBAC-логика остаётся покрытой).
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield overridden_get_session
        finally:
            await overridden_get_session.close()

    async def override_get_current_user() -> UserSecuritySchema:
        return test_user

    app.dependency_overrides[get_session] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield app
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def override_auth_for_no_db_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяет broker-auth в тестах, которым не нужна БД."""
    if not request.node.get_closest_marker("no_db"):
        return

    async def fake_check_token(token: str) -> UserSecuritySchema:
        """Детерминированный авторизованный пользователь для no_db-тестов."""
        return UserSecuritySchema(
            user_id=test_settings.TEST_USER_ID,
            permissions=_all_test_permissions(),
            access_token=token,
        )

    monkeypatch.setattr(security, "check_token", fake_check_token)


@pytest.fixture
async def client(overridden_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент поверх ASGI-приложения (без реального сокета)."""
    async with AsyncClient(
        transport=ASGITransport(app=overridden_app),
        base_url="http://test/",
        headers={"Authorization": f"Bearer {test_settings.TEST_AUTH_TOKEN}"},
        timeout=1,
    ) as async_client:
        yield async_client


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Function]) -> None:
    """Добавляет DB-фикстуру ко всем тестам, кроме помеченных ``@pytest.mark.no_db``.

    Autouse не подходит: он добавил бы фикстуру в конец списка, а сессия
    из `overridden_get_session` должна закрыться до отката миграций.
    """
    for item in items:
        if item.get_closest_marker("no_db"):
            continue
        item.fixturenames = ["overridden_get_session", *item.fixturenames]


def _all_test_permissions() -> set[str]:
    """Все permissions, используемые тестами."""
    return {value for name, value in vars(MyEntityPermissions).items() if name.isupper()}
