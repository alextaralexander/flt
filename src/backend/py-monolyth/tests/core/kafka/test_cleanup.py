"""Уборка доставленных сообщений: outbox старше 7 суток, inbox старше 30 суток (SYS-04-R24, R26)."""

from datetime import timedelta

import pytest
from sqlalchemy import Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import new_id
from app.core.kafka.cleanup import delivery_cleanup_schedules
from app.core.kafka.scheduler import Scheduler
from app.core.modules import ModuleDefinition
from app.core.time import Clock
from tests.core.kafka.conftest import OUTBOX_SCHEMA


async def _count(maker: async_sessionmaker[AsyncSession], table: Table) -> int:
    async with maker() as session:
        return int(await session.scalar(select(func.count()).select_from(table)) or 0)


def _outbox_row(published_days_ago: int | None) -> dict[str, object]:
    now = Clock().now()
    return {
        "id": new_id(),
        "topic": f"flt.{OUTBOX_SCHEMA}.x.v1",
        "key": "k",
        "event_type": f"{OUTBOX_SCHEMA}.x",
        "event_version": 1,
        "body": {},
        "occurred_at": now,
        "published_at": None if published_days_ago is None else now - timedelta(days=published_days_ago),
    }


@pytest.mark.req("SYS-04-R24")
async def test_cleanup_removes_only_old_delivered_rows(
    outbox: Table, inbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Удаляются опубликованные строки outbox старше 7 суток и записи inbox старше 30 суток; остальные остаются."""
    # - Arrange -
    async with session_maker() as session, session.begin():
        await session.execute(insert(outbox), [_outbox_row(8), _outbox_row(1), _outbox_row(None)])
        now = Clock().now()
        await session.execute(
            insert(inbox),
            [
                {"consumer": "c", "event_id": new_id(), "processed_at": now - timedelta(days=31)},
                {"consumer": "c", "event_id": new_id(), "processed_at": now - timedelta(days=1)},
            ],
        )
    module = ModuleDefinition(name=OUTBOX_SCHEMA, metadata=outbox.metadata, outbox=outbox)

    # - Act -
    schedules = delivery_cleanup_schedules(module, session_maker)
    for schedule in schedules:
        await schedule.handler()

    # - Assert -
    assert {schedule.name for schedule in schedules} == {"core_outbox_cleanup", "core_inbox_cleanup"}
    assert await _count(session_maker, outbox) == 2
    assert await _count(session_maker, inbox) == 1


@pytest.mark.req("SYS-04-R26")
@pytest.mark.no_db
def test_scheduler_registers_cleanup_for_each_module(outbox: Table) -> None:
    """Планировщик включает задачи уборки от имени модулей с outbox и inbox."""
    module = ModuleDefinition(name=OUTBOX_SCHEMA, metadata=outbox.metadata, outbox=outbox)
    scheduler = Scheduler([module], redis=None, session_maker=None)  # type: ignore[arg-type]
    assert {(name, schedule.name) for name, schedule, _ in scheduler.entries} == {
        (OUTBOX_SCHEMA, "core_outbox_cleanup"),
        (OUTBOX_SCHEMA, "core_inbox_cleanup"),
    }
