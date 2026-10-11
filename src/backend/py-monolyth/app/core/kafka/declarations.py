"""Декларации топиков и периодических задач модулей (ADR-004, раздел 3.4; SYS-04-R19, R21, R32).

Модуль объявляет топики в `app/modules/<module>/public/topics.py` (кортеж `TOPICS`) и
периодические задачи в `app/modules/<module>/schedules.py`, а подключает их через поля
`ModuleDefinition.topics` и `ModuleDefinition.schedules`. По декларациям роль `migrate`
создаёт топики и DLQ, а планировщик роли `worker` запускает задачи под блокировкой.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal


TOPIC_EVENT_RE = re.compile(r"^flt\.(?P<module>[a-z][a-z0-9_]*)\.(?P<event>[a-z][a-z0-9_]*)\.v(?P<major>[1-9][0-9]*)$")
TOPIC_JOB_RE = re.compile(
    r"^flt\.(?P<module>[a-z][a-z0-9_]*)\.jobs\.(?P<job>[a-z][a-z0-9_]*)\.v(?P<major>[1-9][0-9]*)$"
)
SCHEDULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_PARTITIONS = 6
DEFAULT_RETENTION = timedelta(days=7)
DLQ_RETENTION = timedelta(days=30)
MAX_SCHEDULE_LOCK_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class TopicDeclaration:
    """Топик модуля (SYS-04-R21).

    Attributes:
        name: `flt.<module>.<event>.v<N>` или `flt.<module>.jobs.<job>.v<N>` (SYS-04-R19).
        kind: `event` или `job`.
        visibility: `internal` — читает только модуль-владелец; `public` — и другие модули.
        partitions: Число партиций.
        retention: Срок хранения сообщений.
        message_model: Pydantic-модель сообщения (подкласс `BaseEvent` или схема команды).
        description: Описание для AsyncAPI.
    """

    name: str
    kind: Literal["event", "job"] = "event"
    visibility: Literal["internal", "public"] = "internal"
    partitions: int = DEFAULT_PARTITIONS
    retention: timedelta = DEFAULT_RETENTION
    message_model: type[Any] | None = None
    description: str = ""
    dlq_retention: timedelta = field(default=DLQ_RETENTION, init=False)

    def __post_init__(self) -> None:
        """Проверяет имя по виду топика, видимость заданий и параметры."""
        pattern = TOPIC_JOB_RE if self.kind == "job" else TOPIC_EVENT_RE
        if pattern.match(self.name) is None or (self.kind == "event" and ".jobs." in self.name):
            raise ValueError(f"Топик {self.name!r} вида {self.kind!r} не соответствует шаблону SYS-04-R19.")
        if self.kind == "job" and self.visibility != "internal":
            raise ValueError(f"Топик заданий {self.name!r} может быть только internal (SYS-04-R21).")
        if self.partitions < 1 or self.retention <= timedelta(0):
            raise ValueError(f"Топик {self.name!r}: partitions ≥ 1 и retention > 0 (SYS-04-R21).")

    @property
    def module(self) -> str:
        """Модуль-владелец — второй сегмент имени."""
        return self.name.split(".")[1]

    @property
    def dlq(self) -> str:
        """Dead letter topic `<topic>.dlq` (SYS-04-R19, R27)."""
        return f"{self.name}.dlq"


@dataclass(frozen=True)
class ScheduleDeclaration:
    """Периодическая задача модуля (SYS-04-R32).

    Attributes:
        name: Имя задачи в snake_case.
        cron: Расписание cron из пяти полей.
        handler: Идемпотентная корутина без аргументов.
        lock_ttl: TTL блокировки — интервал задачи, не более 24 ч.
    """

    name: str
    cron: str
    handler: Callable[[], Awaitable[None]]
    lock_ttl: timedelta

    def __post_init__(self) -> None:
        """Проверяет имя, формат cron и TTL блокировки."""
        if SCHEDULE_NAME_RE.match(self.name) is None:
            raise ValueError(f"Задача {self.name!r}: name — snake_case (SYS-04-R32).")
        if len(self.cron.split()) != 5:
            raise ValueError(f"Задача {self.name!r}: cron должен состоять из 5 полей.")
        if not timedelta(0) < self.lock_ttl <= MAX_SCHEDULE_LOCK_TTL:
            raise ValueError(f"Задача {self.name!r}: lock_ttl от 0 до 24 ч (SYS-04-R32, SYS-05-R13).")

    def lock_name(self, module: str) -> str:
        """Имя распределённой блокировки задачи `shared_kernel:lock:schedule:<module>.<name>`."""
        return f"shared_kernel:lock:schedule:{module}.{self.name}"
