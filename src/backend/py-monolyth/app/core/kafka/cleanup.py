"""Уборка доставленных сообщений Kafka в схемах модулей (SYS-04-R24, R26).

Shared kernel регистрирует от имени каждого модуля периодические задачи планировщика:
`core_outbox_cleanup` удаляет опубликованные строки outbox старше 7 суток,
`core_inbox_cleanup` — записи `processed_events` старше 30 суток. Задачи идемпотентны и
выполняются раз в сутки под блокировкой планировщика.
"""

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.kafka.declarations import ScheduleDeclaration
from app.core.modules import ModuleDefinition
from app.core.time import Clock


OUTBOX_RETENTION = timedelta(days=7)
INBOX_RETENTION = timedelta(days=30)
CLEANUP_CRON = "17 3 * * *"
CLEANUP_LOCK_TTL = timedelta(hours=1)


def delivery_cleanup_schedules(
    module: ModuleDefinition, session_maker: async_sessionmaker[AsyncSession]
) -> tuple[ScheduleDeclaration, ...]:
    """Задачи уборки outbox и inbox модуля (только для объявленных у него таблиц)."""
    schedules: list[ScheduleDeclaration] = []
    outbox = module.outbox
    inbox = module.metadata.tables.get(f"{module.name}.processed_events")

    if outbox is not None:

        async def purge_outbox() -> None:
            """Удаляет опубликованные строки outbox старше 7 суток."""
            border = Clock().now() - OUTBOX_RETENTION
            async with session_maker() as session, session.begin():
                await session.execute(delete(outbox).where(outbox.c.published_at < border))

        schedules.append(
            ScheduleDeclaration(
                name="core_outbox_cleanup", cron=CLEANUP_CRON, handler=purge_outbox, lock_ttl=CLEANUP_LOCK_TTL
            )
        )

    if inbox is not None:

        async def purge_inbox() -> None:
            """Удаляет записи inbox старше 30 суток."""
            border = Clock().now() - INBOX_RETENTION
            async with session_maker() as session, session.begin():
                await session.execute(delete(inbox).where(inbox.c.processed_at < border))

        schedules.append(
            ScheduleDeclaration(
                name="core_inbox_cleanup", cron=CLEANUP_CRON, handler=purge_inbox, lock_ttl=CLEANUP_LOCK_TTL
            )
        )
    return tuple(schedules)
