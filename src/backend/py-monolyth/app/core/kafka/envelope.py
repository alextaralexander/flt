"""Конверт доменного события и команда фонового задания (ADR-004, раздел 3.4; SYS-04-R20, R29).

`EventEnvelope[PayloadT]` — тело сообщения события в Kafka; события модулей объявляются
подклассами `BaseEvent` в `app/modules/<module>/public/events.py` с атрибутами класса
`event_type`, `event_version`, `topic`, `aggregate_type`; конверт собирает `BaseEvent.envelope()`.
`JobCommand[PayloadT]` — тело команды задания `flt.<module>.jobs.<job>.v<N>`. Модели игнорируют
неизвестные поля (совместимые изменения схем, SYS-04-R30) и совпадают со схемами
`Analytics/Specs/_system/asyncapi-common.yaml` (SYS-04-R33).
"""

import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

from app.core.ids import new_id
from app.core.time import Clock


EVENT_TYPE_RE = re.compile(r"^(?P<module>[a-z][a-z0-9_]*)\.(?P<event>[a-z][a-z0-9_]*)$")


class EventEnvelope[PayloadT](BaseModel):
    """Конверт события Kafka (SYS-04-R20)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: UUID = Field(description="UUID v7 события; равен `outbox.id`.")
    event_type: str = Field(description="`<module>.<event>` без префикса `flt.` и версии.")
    event_version: int = Field(ge=1, description="Минорная версия схемы события.")
    occurred_at: AwareDatetime = Field(description="Время события, UTC.")
    producer: str = Field(description="Модуль-производитель.")
    aggregate_type: str = Field(description="Имя сущности в snake_case.")
    aggregate_id: UUID = Field(description="UUID сущности; ключ сообщения Kafka.")
    correlation_id: UUID = Field(description="`request_id` запроса или `event_id` события-причины.")
    causation_id: UUID | None = Field(description="Событие или команда, непосредственно вызвавшие событие.")
    actor_id: UUID | None = Field(description="Пользователь, совершивший действие; None — система или аноним.")
    payload: PayloadT = Field(description="Нагрузка по схеме события модуля.")

    @field_serializer("occurred_at")
    def _serialize_occurred_at(self, value: datetime) -> str:
        """ISO 8601 в UTC с суффиксом `Z`."""
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BaseEvent[PayloadT: BaseModel](BaseModel):
    """Базовый класс доменного события модуля (SYS-04-R20).

    Подкласс задаёт атрибуты класса; их согласованность проверяется при объявлении:
    `event_type` — `<module>.<event>`, `topic` — топик того же модуля по SYS-04-R19.

    Attributes:
        event_type: Тип события `<module>.<event>`.
        event_version: Минорная версия схемы (≥ 1).
        topic: Имя топика события `flt.<module>.<event>.v<N>`.
        aggregate_type: Имя сущности агрегата в snake_case.
        payload: Нагрузка события.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    event_type: ClassVar[str]
    event_version: ClassVar[int]
    topic: ClassVar[str]
    aggregate_type: ClassVar[str]

    payload: PayloadT

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Проверяет метаданные конкретного события (обобщённые подклассы пропускаются)."""
        super().__init_subclass__(**kwargs)
        if "event_type" not in cls.__dict__:
            return
        from app.core.kafka.declarations import TOPIC_EVENT_RE

        match = EVENT_TYPE_RE.match(cls.event_type)
        if match is None:
            raise TypeError(f"{cls.__name__}: event_type {cls.event_type!r} не в формате <module>.<event>.")
        topic = TOPIC_EVENT_RE.match(getattr(cls, "topic", ""))
        if topic is None or topic["module"] != match["module"]:
            raise TypeError(f"{cls.__name__}: topic должен быть топиком событий модуля {match['module']!r}.")
        if getattr(cls, "event_version", 0) < 1:
            raise TypeError(f"{cls.__name__}: event_version должен быть не меньше 1.")

    @classmethod
    def producer(cls) -> str:
        """Модуль-производитель — первый сегмент `event_type`."""
        return cls.event_type.split(".", 1)[0]

    def envelope(
        self,
        *,
        aggregate_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        actor_id: UUID | None = None,
        occurred_at: datetime | None = None,
        event_id: UUID | None = None,
    ) -> EventEnvelope[PayloadT]:
        """Собирает конверт события; `event_id` — новый UUID v7, время — `Clock.now()`."""
        return EventEnvelope[PayloadT](
            event_id=event_id or new_id(),
            event_type=self.event_type,
            event_version=self.event_version,
            occurred_at=occurred_at or Clock().now(),
            producer=self.producer(),
            aggregate_type=self.aggregate_type,
            aggregate_id=aggregate_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor_id=actor_id,
            payload=self.payload,
        )


class JobCommand[PayloadT](BaseModel):
    """Команда фонового задания (SYS-04-R29); ключ сообщения — `job_id`."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    job_id: UUID = Field(description="ID записи `<module>.jobs`.")
    kind: str = Field(description="Вид задания.")
    payload: PayloadT = Field(description="Параметры задания.")
    attempt: int = Field(ge=1, description="Номер попытки.")
