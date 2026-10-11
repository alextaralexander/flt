"""Планировщик периодических задач роли `worker` (ADR-004, раздел 3.4; SYS-04-R32).

Каждые 10 с планировщик сверяет текущую минуту с расписаниями `ModuleDefinition.schedules`.
Задача запускается только у того инстанса, который захватил ключ `shared_kernel:lock:schedule:
<module>.<task>` (`SET NX` с TTL = `lock_ttl`); ключ не снимается до истечения TTL, поэтому
запуск в ту же минуту на другом инстансе или при следующей проверке не повторяется. Запуски
пишутся в `<module>.scheduled_runs`, если модуль объявил эту таблицу (`scheduled_runs_table`).
Задачи обязаны быть идемпотентными и укладываться в `lock_ttl`.
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, MetaData, Table, Text, insert, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.dao.caching import ModuleRedis, RedisUnavailableError
from app.core.ids import new_id
from app.core.kafka.declarations import ScheduleDeclaration
from app.core.logging.context import app_logger
from app.core.modules import ModuleDefinition
from app.core.time import Clock


TICK_SECONDS = 10.0
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def scheduled_runs_table(metadata: MetaData) -> Table:
    """Журнал запусков `<module>.scheduled_runs` (SYS-04-R32)."""
    return Table(
        "scheduled_runs",
        metadata,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("task", Text, nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("status", Text, nullable=False),
        Column("error", Text, nullable=True),
        info={"flt_technical": True},
    )


def _field_values(field: str, low: int, high: int) -> set[int]:
    """Значения одного поля cron: `*`, `a`, `a-b`, списки через запятую и шаг `/n`."""
    values: set[int] = set()
    for part in field.split(","):
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)
        values.update(range(start, end + 1, step))
    return values


def cron_matches(expr: str, moment: datetime) -> bool:
    """Совпадает ли минута `moment` (UTC) с выражением cron из пяти полей.

    День месяца и день недели при ограничении обоих полей сочетаются по «или», как в cron;
    день недели 0 и 7 — воскресенье.
    """
    fields = expr.split()
    sets = [_field_values(field, *bounds) for field, bounds in zip(fields, _FIELD_RANGES, strict=True)]
    weekday = (moment.weekday() + 1) % 7
    dow_values = {0 if value == 7 else value for value in sets[4]}
    dom_match = moment.day in sets[2]
    dow_match = weekday in dow_values
    both_restricted = fields[2] != "*" and fields[4] != "*"
    day_match = (dom_match or dow_match) if both_restricted else (dom_match and dow_match)
    return moment.minute in sets[0] and moment.hour in sets[1] and moment.month in sets[3] and day_match


class Scheduler:
    """Планировщик задач модулей реестра.

    Args:
        modules: Модули реестра.
        redis: `ModuleRedis` с префиксом `shared_kernel` (ключи блокировок запусков).
        session_maker: Фабрика сессий для журнала `scheduled_runs`.
    """

    def __init__(
        self,
        modules: Sequence[ModuleDefinition],
        redis: ModuleRedis,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        """Собирает задачи модулей и их журналы запусков."""
        self.redis = redis
        self.session_maker = session_maker
        from app.core.kafka.cleanup import delivery_cleanup_schedules

        self.entries: list[tuple[str, ScheduleDeclaration, Table | None]] = [
            (module.name, schedule, module.metadata.tables.get(f"{module.name}.scheduled_runs"))
            for module in modules
            for schedule in (*module.schedules, *delivery_cleanup_schedules(module, session_maker))
        ]

    async def tick(self, now: datetime | None = None) -> None:
        """Одна проверка расписания: запускает задачи, чья минута наступила и ключ запуска свободен."""
        moment = (now or Clock().now()).replace(second=0, microsecond=0)
        for module, schedule, runs in self.entries:
            if not cron_matches(schedule.cron, moment):
                continue
            key = schedule.lock_name(module).removeprefix("shared_kernel:")
            try:
                acquired = await self.redis.set(key, uuid4().hex, ttl=schedule.lock_ttl, nx=True)
            except RedisUnavailableError:
                app_logger.warning("Планировщик: Redis недоступен, запуск пропущен", task=f"{module}.{schedule.name}")
                continue
            if acquired:
                await self._run(module, schedule, runs)

    async def _run(self, module: str, schedule: ScheduleDeclaration, runs: Table | None) -> None:
        """Выполняет задачу и пишет запуск в журнал; ошибка задачи не останавливает остальные."""
        run_id = new_id()
        if runs is not None:
            async with self.session_maker() as session, session.begin():
                await session.execute(
                    insert(runs).values(id=run_id, task=schedule.name, started_at=Clock().now(), status="running")
                )
        status, error = "succeeded", None
        try:
            await schedule.handler()
        except Exception as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            app_logger.error(
                "Планировщик: задача упала", task=f"{module}.{schedule.name}", error_type=type(exc).__name__
            )
        if runs is not None:
            async with self.session_maker() as session, session.begin():
                await session.execute(
                    update(runs)
                    .where(runs.c.id == run_id)
                    .values(finished_at=Clock().now(), status=status, error=error)
                )

    async def run(self, stop: asyncio.Event) -> None:
        """Цикл планировщика до `stop`: проверка каждые 10 с."""
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                continue
