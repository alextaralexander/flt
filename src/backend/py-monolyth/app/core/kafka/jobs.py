"""Фоновые задания модулей: таблица `<module>.jobs`, команда через outbox, выполнение воркером (SYS-04-R29).

Роль `api` создаёт задание `JobService.enqueue`: запись `queued` и команда `JobCommand` в топик
`flt.<module>.jobs.<job>.v<N>` через outbox в одной транзакции. Воркер выполняет команду
`JobRunner.run`: переводит запись в `running` оптимистично по `version` (повторная или
параллельная доставка не запускает работу второй раз), передаёт работе `JobContext` для прогресса и
проверки отмены и записывает `succeeded`, `failed` или `cancelled`. Отмена — статус `cancelled` в
PostgreSQL и ключ `<module>:job_cancel:<id>` в Redis на 1 ч; работа проверяет её в `checkpoint()`.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.dao.caching import ModuleRedis, RedisUnavailableError
from app.core.ids import new_id
from app.core.kafka.envelope import JobCommand
from app.core.kafka.outbox import OutboxPublisher
from app.core.logging.context import app_logger


CANCEL_FLAG_TTL = timedelta(hours=1)


class JobStatus(StrEnum):
    """Статус фонового задания."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCancelledError(Exception):
    """Задание отменено; бросает `JobContext.checkpoint()`."""


def jobs_table(metadata: MetaData) -> Table:
    """Таблица `<module>.jobs` (SYS-04-R29)."""
    return Table(
        "jobs",
        metadata,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("kind", Text, nullable=False),
        Column("status", Text, nullable=False),
        Column("progress", JSONB, nullable=True),
        Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("result", JSONB, nullable=True),
        Column("error", JSONB, nullable=True),
        Column("run_after", DateTime(timezone=True), nullable=True),
        Column("attempts", Integer, nullable=False, server_default=text("0")),
        Column("owner_user_id", PG_UUID(as_uuid=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("version", Integer, nullable=False, server_default=text("1")),
        info={"flt_technical": True},
    )


class JobService:
    """Создание и отмена заданий модуля в транзакции вызывающего.

    Args:
        table: Таблица `jobs` модуля.
        outbox: Таблица outbox модуля.
    """

    def __init__(self, table: Table, outbox: Table) -> None:
        """Привязывает сервис к таблицам модуля."""
        self.table = table
        self.publisher = OutboxPublisher(outbox)

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        kind: str,
        topic: str,
        payload: dict[str, Any],
        owner_user_id: UUID | None = None,
    ) -> UUID:
        """Создаёт задание `queued` и команду в outbox; возвращает `job_id`."""
        job_id = new_id()
        await session.execute(
            insert(self.table).values(
                id=job_id, kind=kind, status=JobStatus.QUEUED, payload=payload, owner_user_id=owner_user_id
            )
        )
        command = JobCommand[dict[str, Any]](job_id=job_id, kind=kind, payload=payload, attempt=1)
        await self.publisher.send_command(session, topic, command)
        return job_id

    async def cancel(self, session: AsyncSession, redis: ModuleRedis, job_id: UUID) -> bool:
        """Отменяет незавершённое задание; возвращает False, если отменять уже нечего."""
        result = await session.execute(
            update(self.table)
            .where(self.table.c.id == job_id, self.table.c.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
            .values(status=JobStatus.CANCELLED, updated_at=func.now(), version=self.table.c.version + 1)
            .returning(self.table.c.id)
        )
        if result.first() is None:
            return False
        try:
            await redis.set(f"job_cancel:{job_id}", "1", ttl=CANCEL_FLAG_TTL)
        except RedisUnavailableError:
            app_logger.warning("Отмена задания: Redis недоступен, воркер увидит отмену по статусу в PostgreSQL")
        return True


class JobContext:
    """Контекст выполнения задания: прогресс и проверка отмены."""

    def __init__(self, runner: JobRunner, job_id: UUID) -> None:
        """Связывает контекст с заданием."""
        self.runner = runner
        self.job_id = job_id

    async def progress(self, value: dict[str, Any]) -> None:
        """Сохраняет прогресс задания (грубые шаги, не токены LLM)."""
        table = self.runner.table
        async with self.runner.session_maker() as session, session.begin():
            await session.execute(
                update(table).where(table.c.id == self.job_id).values(progress=value, updated_at=func.now())
            )

    async def checkpoint(self) -> None:
        """Проверка отмены между шагами работы.

        Raises:
            JobCancelledError: Задание отменено (флаг в Redis или статус в PostgreSQL).
        """
        try:
            if await self.runner.redis.get(f"job_cancel:{self.job_id}") is not None:
                raise JobCancelledError
        except RedisUnavailableError:
            pass
        table = self.runner.table
        async with self.runner.session_maker() as session:
            status = await session.scalar(select(table.c.status).where(table.c.id == self.job_id))
        if status == JobStatus.CANCELLED:
            raise JobCancelledError


type JobWork = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobRunner:
    """Выполнение команд заданий модуля в роли `worker`.

    Args:
        module: Имя модуля.
        table: Таблица `jobs` модуля.
        session_maker: Фабрика сессий.
        redis: `ModuleRedis` модуля (флаги отмены).
    """

    def __init__(
        self, module: str, table: Table, session_maker: async_sessionmaker[AsyncSession], redis: ModuleRedis
    ) -> None:
        """Сохраняет зависимости."""
        self.module = module
        self.table = table
        self.session_maker = session_maker
        self.redis = redis

    async def run(self, command: JobCommand[Any], work: JobWork) -> JobStatus | None:
        """Выполняет задание один раз; None — задание уже взято другим воркером или завершено."""
        table = self.table
        async with self.session_maker() as session, session.begin():
            row = (
                await session.execute(select(table.c.status, table.c.version).where(table.c.id == command.job_id))
            ).first()
            if row is None or row.status != JobStatus.QUEUED:
                return None
            claimed = await session.execute(
                update(table)
                .where(table.c.id == command.job_id, table.c.version == row.version)
                .values(
                    status=JobStatus.RUNNING,
                    attempts=table.c.attempts + 1,
                    version=table.c.version + 1,
                    updated_at=func.now(),
                )
                .returning(table.c.id)
            )
            if claimed.first() is None:
                return None

        status, values = JobStatus.SUCCEEDED, {}
        try:
            values = {"result": await work(JobContext(self, command.job_id))}
        except JobCancelledError:
            status = JobStatus.CANCELLED
        except Exception as exc:
            status, values = JobStatus.FAILED, {"error": {"type": type(exc).__name__, "message": str(exc)[:1000]}}
            app_logger.error(
                "Фоновое задание упало", module=self.module, kind=command.kind, error_type=type(exc).__name__
            )

        async with self.session_maker() as session, session.begin():
            await session.execute(
                update(table)
                .where(table.c.id == command.job_id, table.c.status == JobStatus.RUNNING)
                .values(status=status, updated_at=func.now(), version=table.c.version + 1, **values)
            )
        return status
