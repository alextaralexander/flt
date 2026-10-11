"""Fixture тестов outbox и inbox: временная схема `core_outbox_test` с таблицами outbox и processed_events."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import MetaData, Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.dao.db_helpers.base import module_metadata
from app.core.kafka.inbox import processed_events_table
from app.core.kafka.jobs import jobs_table
from app.core.kafka.outbox import outbox_table
from configs.settings import settings
from tests.settings import test_settings
from tests.support.stand_guard import assert_test_database


OUTBOX_SCHEMA = "core_outbox_test"


@pytest_asyncio.fixture
async def outbox_engine() -> AsyncIterator[AsyncEngine]:
    """Отдельный engine тестовой базы (пул на тест)."""
    assert_test_database(test_mode=test_settings.TEST_MODE, database=settings.PG_DATABASE)
    engine = create_async_engine(settings.sqlalchemy_database_uri)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def outbox(outbox_engine: AsyncEngine) -> AsyncIterator[Table]:
    """Таблица outbox в отдельной схеме: создаётся перед тестом и удаляется после."""
    metadata: MetaData = module_metadata(OUTBOX_SCHEMA)
    table = outbox_table(metadata)
    processed_events_table(metadata)
    jobs_table(metadata)
    async with outbox_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{OUTBOX_SCHEMA}" CASCADE'))
        await connection.execute(text(f'CREATE SCHEMA "{OUTBOX_SCHEMA}"'))
        await connection.run_sync(metadata.create_all)
    yield table
    async with outbox_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{OUTBOX_SCHEMA}" CASCADE'))


@pytest_asyncio.fixture
async def inbox(outbox: Table) -> Table:
    """Таблица `processed_events` той же схемы (создаётся вместе с outbox)."""
    assert outbox.metadata.schema is not None
    return outbox.metadata.tables[f"{OUTBOX_SCHEMA}.processed_events"]


@pytest_asyncio.fixture
async def jobs(outbox: Table) -> Table:
    """Таблица `jobs` той же схемы."""
    return outbox.metadata.tables[f"{OUTBOX_SCHEMA}.jobs"]


@pytest_asyncio.fixture
async def session_maker(outbox_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий тестовой базы."""
    return async_sessionmaker(outbox_engine, expire_on_commit=False)
