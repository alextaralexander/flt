"""Transactional outbox: запись событий и команд в `<module>.outbox` (ADR-004, раздел 2.3; SYS-04-R22, R24).

Модуль объявляет таблицу фабрикой `outbox_table(metadata)` в своих моделях (миграция модуля
создаёт её в схеме модуля) и публикует через `OutboxPublisher(table)` в той же сессии и
транзакции, что и изменение данных. В Kafka сообщения отправляет relay роли `worker`
(`app.core.kafka.relay`). Прямой `broker.publish` в модулях запрещён (контракт import-linter 6).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    insert,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http.context import current_request_id
from app.core.ids import new_id
from app.core.kafka.declarations import TOPIC_EVENT_RE, TOPIC_JOB_RE
from app.core.kafka.envelope import BaseEvent, JobCommand
from app.core.time import Clock


CONTENT_TYPE = "application/json"


def outbox_table(metadata: MetaData) -> Table:
    """Таблица `<module>.outbox` в схеме метаданных модуля (DDL — SYS-04, пример 4).

    Args:
        metadata: Метаданные модуля (`module_metadata("<module>")`).

    Returns:
        Таблица outbox; техническая таблица без обязательных колонок `EntityBase` (SYS-05-R7).
    """
    table = Table(
        "outbox",
        metadata,
        Column("id", PG_UUID(as_uuid=True), primary_key=True, comment="UUID v7 = event_id"),
        Column("topic", Text, nullable=False),
        Column("key", Text, nullable=False, comment="aggregate_id или job_id"),
        Column("event_type", Text, nullable=False),
        Column("event_version", Integer, nullable=False),
        Column("headers", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("body", JSONB, nullable=False, comment="EventEnvelope или JobCommand целиком"),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("published_at", DateTime(timezone=True), nullable=True),
        Column("attempts", Integer, nullable=False, server_default=text("0")),
        Column("last_error", Text, nullable=True),
        info={"flt_technical": True},
    )
    Index(
        f"ix_{metadata.schema}_outbox_unpublished",
        table.c.id,
        postgresql_where=table.c.published_at.is_(None),
    )
    return table


def _correlation_id(correlation_id: UUID | None) -> UUID:
    """`correlation_id` из аргумента, иначе `request_id` текущего запроса, иначе новый UUID v7."""
    if correlation_id is not None:
        return correlation_id
    request_id = current_request_id()
    if request_id:
        try:
            return UUID(request_id)
        except ValueError:
            pass
    return new_id()


class OutboxPublisher:
    """Запись событий и команд модуля в его outbox в транзакции вызывающего (SYS-04-R24).

    Args:
        table: Таблица outbox модуля (`outbox_table(...)`); модуль — схема таблицы.
    """

    def __init__(self, table: Table) -> None:
        """Привязывает издателя к outbox модуля."""
        if table.schema is None:
            raise ValueError("Таблица outbox должна лежать в схеме модуля.")
        self.table = table
        self.module: str = table.schema

    def _check_topic(self, topic: str, *, job: bool) -> None:
        """Модуль публикует только в свои топики нужного вида (SYS-04-R19)."""
        match = (TOPIC_JOB_RE if job else TOPIC_EVENT_RE).match(topic)
        if match is None or match["module"] != self.module or (not job and ".jobs." in topic):
            raise ValueError(f"Модуль {self.module} не может публиковать в топик {topic} (SYS-04-R19).")

    async def publish(
        self,
        session: AsyncSession,
        event: BaseEvent[Any],
        *,
        aggregate_id: UUID,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> UUID:
        """Добавляет событие в outbox в текущей транзакции сессии.

        Args:
            session: Сессия модуля с открытой транзакцией изменения данных.
            event: Событие модуля (подкласс `BaseEvent`).
            aggregate_id: UUID агрегата — ключ сообщения Kafka (SYS-04-R22, R25).
            correlation_id: Корреляция; по умолчанию — `request_id` текущего запроса.
            causation_id: Событие или команда-причина.
            actor_id: Пользователь, совершивший действие.

        Returns:
            `event_id` записи.
        """
        self._check_topic(event.topic, job=False)
        envelope = event.envelope(
            aggregate_id=aggregate_id,
            correlation_id=_correlation_id(correlation_id),
            causation_id=causation_id,
            actor_id=actor_id,
        )
        headers = {
            "event_id": str(envelope.event_id),
            "event_type": envelope.event_type,
            "event_version": str(envelope.event_version),
            "producer": envelope.producer,
            "content_type": CONTENT_TYPE,
            "request_id": str(envelope.correlation_id),
            "schema": f"{self.module}.{type(event).__name__}",
        }
        await session.execute(
            insert(self.table).values(
                id=envelope.event_id,
                topic=event.topic,
                key=str(aggregate_id),
                event_type=envelope.event_type,
                event_version=envelope.event_version,
                headers=headers,
                body=envelope.model_dump(mode="json"),
                occurred_at=envelope.occurred_at,
            )
        )
        return envelope.event_id

    async def send_command(
        self, session: AsyncSession, topic: str, command: JobCommand[Any], *, correlation_id: UUID | None = None
    ) -> UUID:
        """Добавляет команду задания в outbox; ключ сообщения — `job_id` (SYS-04-R22, R29).

        Returns:
            ID записи outbox.
        """
        self._check_topic(topic, job=True)
        record_id = new_id()
        kind = f"{self.module}.jobs.{command.kind}"
        headers = {
            "event_id": str(record_id),
            "event_type": kind,
            "event_version": "1",
            "producer": self.module,
            "content_type": CONTENT_TYPE,
            "request_id": str(_correlation_id(correlation_id)),
            "schema": f"{self.module}.JobCommand",
        }
        await session.execute(
            insert(self.table).values(
                id=record_id,
                topic=topic,
                key=str(command.job_id),
                event_type=kind,
                event_version=1,
                headers=headers,
                body=command.model_dump(mode="json"),
                occurred_at=Clock().now(),
            )
        )
        return record_id
