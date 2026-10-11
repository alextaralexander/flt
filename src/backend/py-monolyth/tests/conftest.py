"""Главные fixture для тестов.

Аутентификация HTTP-тестов подменяется в одной точке — `get_current_user`
через `dependency_overrides` (fixture `overridden_app`).

БД: тесты интеграционные, ходят в отдельную базу `flt_test` и базу Redis 15 того же
экземпляра, что и стенд local (SYS-10-R4); миграции всех модулей реестра
(`alembic -n <module> upgrade head`, ADR-002) накатываются один раз на сессию и
откатываются в конце.
"""

from collections.abc import AsyncGenerator, Iterator
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.dao.db_helpers.db_connection import get_session
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import get_current_user
from app.core.telemetry import SERVICE_NAME, setup_telemetry
from app.core.time import Clock
from app.main import create_app
from app.modules.registry import MODULES
from configs.settings import settings
from tests.settings import test_settings
from tests.support.clock import FrozenClock
from tests.support.stand_guard import assert_test_database


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


@app.get("/mocked_endpoint/{item_id}")
async def mocked_item_endpoint(item_id: str) -> dict[str, str]:
    """Тестовый endpoint с параметром пути (шаблон маршрута для метрик)."""
    return {"item_id": item_id}


class MockedBody(BaseModel):
    """Тело тестового запроса: обязательное поле для проверки ответа 422."""

    name: str


@app.post("/mocked_body")
async def mocked_body_endpoint(body: MockedBody) -> None:
    """Тестовый endpoint с телом запроса (валидация FastAPI)."""


def alembic_config(module: str) -> Config:
    """Конфигурация Alembic секции модуля из `alembic.ini` (аналог `alembic -n <module>`)."""
    return Config("alembic.ini", ini_section=module)


@pytest.fixture(scope="session")
def db_migrate() -> Iterator[None]:
    """Применение и откат миграций всех модулей реестра в тестовой базе данных.

    - Выполняет `upgrade head` каждого модуля в порядке реестра перед тестами.
    - После тестов откатывает модули в обратном порядке до `base`.
    - Используется на уровне сессии (`scope="session"`), чтобы миграции выполнялись один раз за тестовую сессию.
    """
    # Защита от запуска на рабочей БД: TEST_MODE и база *_test задаёт только оверлей envs/.test.env.
    assert_test_database(test_mode=test_settings.TEST_MODE, database=settings.PG_DATABASE)

    for module in MODULES:
        command.upgrade(alembic_config(module), "head")
    yield
    for module in reversed(MODULES):
        command.downgrade(alembic_config(module), "base")


@pytest_asyncio.fixture
async def overridden_get_session(db_migrate: None) -> AsyncGenerator[AsyncSession]:
    """Сессия тестовой БД, которой подменяется штатная `get_session`."""
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def test_user() -> UserSecuritySchema:
    """Аутентифицированный пользователь со всеми правами модулей реестра."""
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

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
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


@pytest.fixture
async def client(overridden_app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """HTTP-клиент поверх ASGI-приложения (без реального сокета)."""
    async with AsyncClient(
        transport=ASGITransport(app=overridden_app),
        base_url="http://test/",
        headers={"Authorization": f"Bearer {test_settings.TEST_AUTH_TOKEN}"},
        timeout=1,
    ) as async_client:
        yield async_client


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    """Останавливает `Clock` shared kernel на 2026-10-10T12:00:00Z (SYS-10-R17).

    Все экземпляры `Clock` возвращают время управляемых часов: `frozen_clock.set(...)`,
    `frozen_clock.advance(timedelta(...))`. Подмена снимается после теста.
    """
    clock = FrozenClock()

    def frozen_now(self: Clock) -> datetime:
        return clock.now()

    monkeypatch.setattr(Clock, "now", frozen_now)
    return clock


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
    """Все права модулей реестра (`ModuleDefinition.permissions`)."""
    from app.core.modules import load_modules

    return {code for module in load_modules(MODULES) for code in module.permissions}
