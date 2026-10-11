"""Планировщик периодических задач роли `worker` (SYS-04-R32)."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.dao.caching import ModuleRedis
from app.core.dao.db_helpers.base import module_metadata
from app.core.kafka.declarations import ScheduleDeclaration
from app.core.kafka.scheduler import Scheduler, cron_matches, scheduled_runs_table
from app.core.modules import ModuleDefinition
from tests.support.redis_instances import redis_instances  # noqa: F401


pytestmark = pytest.mark.req("SYS-04-R32")

SCHEMA = "core_scheduler_test"
NOW = datetime(2026, 10, 12, 3, 0, 5, tzinfo=UTC)


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("expr", "moment", "expected"),
    [
        ("* * * * *", NOW, True),
        ("0 3 * * *", NOW, True),
        ("0 4 * * *", NOW, False),
        ("*/15 * * * *", NOW.replace(minute=45), True),
        ("*/15 * * * *", NOW.replace(minute=46), False),
        ("0 1-5 * * *", NOW, True),
        ("0 3 * * 1,2", NOW, True),  # 2026-10-12 — понедельник (cron: 1)
        ("0 3 * * 0", NOW, False),
        ("0 3 12 10 *", NOW, True),
    ],
)
def test_cron_matches(expr: str, moment: datetime, expected: bool) -> None:
    """Пять полей cron: `*`, числа, списки, диапазоны и шаг."""
    assert cron_matches(expr, moment) is expected


@pytest.fixture
async def runs_table(outbox_engine: AsyncEngine) -> Table:
    """Схема модуля с таблицей `scheduled_runs`."""
    metadata: MetaData = module_metadata(SCHEMA)
    table = scheduled_runs_table(metadata)
    async with outbox_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await connection.run_sync(metadata.create_all)
    yield table
    async with outbox_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))


async def test_task_runs_once_across_instances_and_is_logged(
    runs_table: Table,
    session_maker: async_sessionmaker[AsyncSession],
    redis_instances: Callable[[], Redis],  # noqa: F811
    redis_clean: None,
) -> None:
    """Два планировщика («инстанса») в одну минуту: задача выполняется один раз, запуск записан в журнал."""
    # - Arrange -
    calls: list[int] = []

    async def purge() -> None:
        calls.append(1)

    schedule = ScheduleDeclaration(name="purge", cron="0 3 * * *", handler=purge, lock_ttl=timedelta(minutes=1))
    module = ModuleDefinition(name=SCHEMA, metadata=runs_table.metadata, schedules=(schedule,))
    schedulers = [
        Scheduler([module], ModuleRedis("shared_kernel", client=redis_instances()), session_maker) for _ in range(2)
    ]

    # - Act -
    await asyncio.gather(*(scheduler.tick(NOW) for scheduler in schedulers))
    await asyncio.gather(*(scheduler.tick(NOW + timedelta(seconds=10)) for scheduler in schedulers))
    await schedulers[0].tick(NOW + timedelta(hours=1))

    # - Assert -
    assert calls == [1]
    async with session_maker() as session:
        rows = (await session.execute(select(runs_table))).all()
    assert [(row.task, row.status) for row in rows] == [("purge", "succeeded")]
    assert rows[0].finished_at is not None


async def test_failed_task_is_logged_and_does_not_stop_others(
    runs_table: Table, session_maker: async_sessionmaker[AsyncSession], raw_test_redis: Redis, redis_clean: None
) -> None:
    """Ошибка задачи пишется в журнал (`failed`, `error`), остальные задачи выполняются."""
    calls: list[str] = []

    async def broken() -> None:
        raise RuntimeError("boom")

    async def healthy() -> None:
        calls.append("healthy")

    module = ModuleDefinition(
        name=SCHEMA,
        metadata=runs_table.metadata,
        schedules=(
            ScheduleDeclaration(name="broken", cron="* * * * *", handler=broken, lock_ttl=timedelta(minutes=1)),
            ScheduleDeclaration(name="healthy", cron="* * * * *", handler=healthy, lock_ttl=timedelta(minutes=1)),
        ),
    )

    await Scheduler([module], ModuleRedis("shared_kernel", client=raw_test_redis), session_maker).tick(NOW)

    assert calls == ["healthy"]
    async with session_maker() as session:
        rows = {row.task: row for row in (await session.execute(select(runs_table))).all()}
    assert rows["broken"].status == "failed"
    assert "boom" in rows["broken"].error


async def test_worker_lifespan_runs_scheduler(redis_clean: None) -> None:
    """Роль `worker` запускает планировщик при старте и останавливает его при выключении."""
    from faststream.kafka import TestKafkaBroker

    from app.main import create_worker_app

    ran = asyncio.Event()

    async def ping() -> None:
        ran.set()

    module = ModuleDefinition(
        name=SCHEMA,
        metadata=module_metadata(SCHEMA),
        schedules=(ScheduleDeclaration(name="ping", cron="* * * * *", handler=ping, lock_ttl=timedelta(minutes=1)),),
    )
    worker = create_worker_app([module], manage_resources=False)

    async with TestKafkaBroker(worker.brokers[0]), worker.start_lifespan_context():
        await asyncio.wait_for(ran.wait(), timeout=5)

    assert ran.is_set()
