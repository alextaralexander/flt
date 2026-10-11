"""Главные fixture и хуки тестов (SYS-10).

Аутентификация HTTP-тестов подменяется в одной точке — `get_current_user`
через `dependency_overrides` (fixture `overridden_app`).

БД: тесты интеграционные, ходят в отдельную базу `flt_test` и базу Redis 15 того же
экземпляра, что и стенд local (SYS-10-R4); миграции всех модулей реестра
(`alembic -n <module> upgrade head`, ADR-002) накатываются один раз на сессию и
откатываются в конце. Тестам с хранилищами (все, кроме `no_db` и `n_instances`) хук сбора
добавляет фикстуры изоляции: `clean_tables` (TRUNCATE таблиц модулей после теста, SYS-10-R5),
`redis_clean` (FLUSHDB базы 15 перед тестом) и `redis_no_persistent_keys` (ключи без TTL,
без префикса или с TTL сверх категории — падение, SYS-10-R6).

Маркеры `ac`, `req`, `n_instances`, `smoke`, `slow`, `quarantine` проверяются при сборе
(`tests/support/markers.py`, SYS-10-R12); тесты стенда N3 без `--stand-url` пропускаются (SYS-05-R45).
"""

import os
import socket
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.container import container
from app.core.dao.caching.redis_conn import close_redis_client, create_redis_client
from app.core.dao.db_helpers.db_connection import get_session
from app.core.mail import MailClient
from app.core.modules import load_modules
from app.core.security.permissions import Grant, Scope
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import get_current_user
from app.core.telemetry import SERVICE_NAME, setup_telemetry
from app.core.time import Clock
from app.main import create_app
from app.modules.registry import MODULES
from configs.redis_config import redis_settings
from configs.settings import settings
from tests.settings import test_settings
from tests.support.clock import FrozenClock
from tests.support.eventually import eventually as eventually_fn
from tests.support.jwt_keys import SigningKeyPair
from tests.support.mail import InMemoryMailClient
from tests.support.markers import marker_errors, quarantine_xfail
from tests.support.redis_keys import find_invalid_keys
from tests.support.stand_guard import assert_test_database, assert_test_redis_db


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
async def clean_tables(db_migrate: None) -> AsyncIterator[None]:
    """Очищает таблицы всех модулей реестра после теста: `TRUNCATE … RESTART IDENTITY CASCADE` (SYS-10-R5)."""
    yield
    tables = [table for module in load_modules(MODULES) for table in module.metadata.sorted_tables]
    if not tables:
        return
    assert_test_database(test_mode=test_settings.TEST_MODE, database=settings.PG_DATABASE)
    names = ", ".join(f'"{table.schema}"."{table.name}"' for table in tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def raw_test_redis() -> AsyncIterator[Redis]:
    """Сырой клиент тестовой базы Redis 15 — только для фикстур и проверок состояния (SYS-10-R4)."""
    assert_test_redis_db(test_mode=test_settings.TEST_MODE, db=redis_settings.REDIS_DB)
    client = create_redis_client(redis_settings)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def redis_clean(raw_test_redis: Redis) -> None:
    """Очищает тестовую базу Redis 15 перед тестом (`FLUSHDB`, SYS-10-R6)."""
    await raw_test_redis.flushdb()


@pytest_asyncio.fixture
async def redis_no_persistent_keys(raw_test_redis: Redis) -> AsyncIterator[None]:
    """После теста падает на ключах Redis без TTL, без префикса модуля или с TTL сверх категории (SYS-10-R6)."""
    yield
    problems = await find_invalid_keys(raw_test_redis, MODULES)
    if problems:
        await raw_test_redis.flushdb()
        pytest.fail(f"Ключи Redis нарушают SYS-05-R12/R13: {problems}", pytrace=False)


@pytest_asyncio.fixture
async def redis_down(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Переключает Redis-клиент процесса на закрытый порт: проверка поведения без Redis (SYS-05-R15).

    До `ModuleRedis` (Г.4) подменяется адрес общего клиента `get_redis_client()`; клиент
    пересоздаётся при входе и выходе, чтобы соединения с рабочим Redis не переиспользовались.
    """
    await close_redis_client()
    monkeypatch.setattr(redis_settings, "REDIS_HOST", "127.0.0.1")
    monkeypatch.setattr(redis_settings, "REDIS_PORT", _closed_local_port())
    yield
    await close_redis_client()


def _closed_local_port() -> int:
    """Порт на 127.0.0.1, который никто не слушает (занят и сразу освобождён)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


@pytest.fixture
def eventually() -> Any:
    """Функция ожидания эффекта опросом с таймаутом вместо фиксированных пауз (SYS-10-R17)."""
    return eventually_fn


@pytest.fixture
def mail_outbox() -> Iterator[InMemoryMailClient]:
    """Письма теста вместо SMTP: подменяет `MailClient` в контейнере shared kernel (SYS-10-R21)."""
    outbox = InMemoryMailClient()
    with container.override(MailClient, outbox):
        yield outbox


@pytest.fixture(scope="session")
def jwt_signing_keys() -> SigningKeyPair:
    """Одноразовая Ed25519-пара ключей подписи JWT тестовой сессии (ADR-006 §3.3; корневой conftest.py)."""
    return SigningKeyPair.from_environ(os.environ)


@pytest_asyncio.fixture
async def overridden_get_session(db_migrate: None) -> AsyncGenerator[AsyncSession]:
    """Сессия тестовой БД, которой подменяется штатная `get_session`."""
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def test_user() -> UserSecuritySchema:
    """Аутентифицированный пользователь со всеми правами модулей реестра (область `any`)."""
    user_id = UUID(test_settings.TEST_USER_ID)
    return UserSecuritySchema(
        user_id=user_id,
        sid=UUID(int=1),
        roles=("learner",),
        permissions=frozenset(Grant(code=code, scope=Scope.ANY).bind(user_id) for code in _all_test_permissions()),
        email_verified=True,
        age_confirmed=True,
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


# Фикстуры изоляции хранилищ: сессия БД закрывается раньше отката миграций (порядок списка).
STORAGE_FIXTURES = ("overridden_get_session", "clean_tables", "redis_clean", "redis_no_persistent_keys")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Опции стенда N3 для тестов `n_instances` (SYS-05-R45, R46): адрес HAProxy и проект compose."""
    parser.addoption(
        "--stand-url",
        default=None,
        help="URL HAProxy стенда N3, например http://127.0.0.1:8080; без опции тесты n_instances пропускаются",
    )
    parser.addoption(
        "--stand-project",
        default=os.environ.get("FLT_STAND_PROJECT", "flt"),
        help="Проект docker compose стенда N3 (контейнеры <project>-api-<n>); по умолчанию flt (SYS-11-R28)",
    )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Проверяет маркеры, ставит карантин и пропуск N3, добавляет фикстуры хранилищ.

    - нарушения правил маркеров (SYS-10-R12, R29, R30; SYS-05-R45) — ошибка сбора;
    - тест в действующем карантине получает `xfail(strict=False)` (SYS-10-R29);
    - тесты `n_instances` без `--stand-url` пропускаются: «нужен стенд N3» (SYS-05-R45);
    - остальным тестам, кроме `no_db`, добавляются фикстуры хранилищ. Autouse не подходит:
      он добавил бы фикстуры в конец списка, а сессия из `overridden_get_session` должна
      закрыться до отката миграций.
    """
    today = date.today()
    stand_url = config.getoption("--stand-url")
    errors: list[str] = []
    for item in items:
        rel_path = item.path.relative_to(config.rootpath).as_posix()
        markers = list(item.iter_markers())
        errors.extend(f"{item.nodeid}: {error}" for error in marker_errors(rel_path, markers, today))

        quarantine = quarantine_xfail(markers, today)
        if quarantine is not None:
            item.add_marker(quarantine)

        if item.get_closest_marker("n_instances"):
            # Тесты стенда по определению ходят по сети к стенду (исключение SYS-10-R37).
            item.add_marker(pytest.mark.enable_socket)
            if not stand_url:
                item.add_marker(pytest.mark.skip(reason="нужен стенд N3: передайте --stand-url (SYS-05-R45)"))
            continue
        if item.get_closest_marker("no_db") or not isinstance(item, pytest.Function):
            continue
        missing = [name for name in STORAGE_FIXTURES if name not in item.fixturenames]
        item.fixturenames = [*missing, *item.fixturenames]

    if errors:
        raise pytest.UsageError("Нарушения правил маркеров pytest:\n" + "\n".join(errors))


def _all_test_permissions() -> set[str]:
    """Все права модулей реестра (`ModuleDefinition.permissions`)."""
    from app.core.modules import load_modules

    return {code for module in load_modules(MODULES) for code in module.permissions}
