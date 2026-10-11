"""Идемпотентный консьюмер Kafka: inbox, ретраи и dead letter topic (ADR-004, раздел 3.4; SYS-04-R26, R27).

Модуль объявляет таблицу `processed_events_table(metadata)` в своих моделях. Обработчик
сообщения выполняется через `IdempotentConsumer.handle(message, handler)` в одной транзакции
модуля: `INSERT … processed_events ON CONFLICT DO NOTHING`; конфликт — дубликат, обработчик не
вызывается; иначе — изменения обработчика (и его события в outbox) и запись inbox фиксируются
вместе, ack Kafka — после commit. При исключении попытка откатывается и повторяется через 1, 5,
25 с; `NonRetryableError` и ошибки валидации сразу уходят в `<topic>.dlq` с заголовками ошибки,
как и сообщение после исчерпания попыток. Исходное сообщение после записи в DLQ подтверждается.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from faststream.kafka import KafkaMessage
from prometheus_client import Counter
from pydantic import ValidationError
from sqlalchemy import Column, DateTime, MetaData, PrimaryKeyConstraint, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.contextvars import bound_contextvars

from app.core.container import container
from app.core.dao.db_helpers.db_connection import get_session_maker
from app.core.kafka.relay import OutboxSink
from app.core.logging.context import app_logger
from app.core.time import Clock


RETRY_DELAYS: tuple[float, ...] = (1, 5, 25)
MAX_ERROR_LENGTH = 1024

DUPLICATES = Counter("flt_kafka_duplicates_total", "Повторные доставки, пропущенные inbox.", ["consumer"])
DLQ_MESSAGES = Counter("flt_kafka_dlq_messages_total", "Сообщения, отправленные в DLQ.", ["topic", "consumer"])


class NonRetryableError(Exception):
    """Ошибка обработки, которую бессмысленно повторять: сообщение сразу уходит в DLQ (SYS-04-R27)."""


class MissingEventIdError(NonRetryableError):
    """У сообщения нет заголовка `event_id` — дедупликация невозможна."""


class Outcome(StrEnum):
    """Результат обработки сообщения."""

    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    DEAD_LETTERED = "dead_lettered"


def processed_events_table(metadata: MetaData) -> Table:
    """Таблица inbox `<module>.processed_events` (DDL — SYS-04, пример 4)."""
    return Table(
        "processed_events",
        metadata,
        Column("consumer", Text, nullable=False),
        Column("event_id", PG_UUID(as_uuid=True), nullable=False),
        Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        PrimaryKeyConstraint("consumer", "event_id"),
        info={"flt_technical": True},
    )


@dataclass
class ConsumedMessage:
    """Полученное сообщение Kafka в виде, не зависящем от клиента.

    Attributes:
        topic: Исходный топик.
        partition: Партиция.
        offset: Смещение.
        key: Ключ сообщения (строка) или None.
        value: Тело сообщения как есть.
        headers: Заголовки сообщения (строки UTF-8).
    """

    topic: str
    partition: int
    offset: int
    key: str | None
    value: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_kafka(cls, message: KafkaMessage) -> ConsumedMessage:
        """Собирает сообщение из `KafkaMessage` FastStream (подписчик модуля)."""
        raw = message.raw_message
        key = getattr(raw, "key", None)
        return cls(
            topic=getattr(raw, "topic", ""),
            partition=int(getattr(raw, "partition", 0) or 0),
            offset=int(getattr(raw, "offset", 0) or 0),
            key=key.decode() if isinstance(key, bytes) else key,
            value=message.body if isinstance(message.body, bytes) else bytes(message.body),
            headers={str(name): str(value) for name, value in message.headers.items()},
        )


type Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


class IdempotentConsumer:
    """Обработка сообщений одним консьюмером модуля с inbox, ретраями и DLQ.

    Args:
        consumer: Имя консьюмера `<module>.<handler>` (ключ inbox и группы).
        table: Таблица `processed_events` модуля.
        session_maker: Фабрика сессий.
        dlq: Приёмник сообщений DLQ (продюсер Kafka).
        delays: Задержки между попытками (по умолчанию 1, 5, 25 с).
        sleep: Функция ожидания (подменяется в тестах).
    """

    def __init__(
        self,
        consumer: str,
        table: Table,
        session_maker: async_sessionmaker[AsyncSession],
        dlq: OutboxSink,
        *,
        delays: Sequence[float] = RETRY_DELAYS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Сохраняет зависимости консьюмера."""
        self.consumer = consumer
        self.table = table
        self.session_maker = session_maker
        self.dlq = dlq
        self.delays = tuple(delays)
        self.sleep = sleep

    async def handle(self, message: ConsumedMessage, handler: Handler) -> Outcome:
        """Обрабатывает сообщение ровно один раз по `event_id`; при отказе — DLQ.

        Args:
            message: Полученное сообщение.
            handler: Обработчик `(session, body) -> None`; выполняется в транзакции с записью inbox.

        Returns:
            Итог обработки; во всех случаях исходное сообщение можно подтверждать.
        """
        context = {"consumer": self.consumer, "request_id": message.headers.get("request_id")}
        with bound_contextvars(**{name: value for name, value in context.items() if value}):
            raw_event_id = message.headers.get("event_id")
            try:
                event_id = UUID(raw_event_id) if raw_event_id else None
            except ValueError:
                event_id = None
            if event_id is None:
                await self._dead_letter(message, MissingEventIdError("message has no valid event_id header"), 1)
                return Outcome.DEAD_LETTERED

            attempt = 0
            while True:
                attempt += 1
                try:
                    return await self._attempt(event_id, message, handler)
                except (NonRetryableError, ValidationError, json.JSONDecodeError) as exc:
                    await self._dead_letter(message, exc, attempt)
                    return Outcome.DEAD_LETTERED
                except Exception as exc:
                    if attempt > len(self.delays):
                        await self._dead_letter(message, exc, attempt)
                        return Outcome.DEAD_LETTERED
                    app_logger.warning(
                        "Kafka consumer: повтор обработки",
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        event_id=str(event_id),
                    )
                    await self.sleep(self.delays[attempt - 1])

    async def _attempt(self, event_id: UUID, message: ConsumedMessage, handler: Handler) -> Outcome:
        """Одна попытка: запись inbox и обработчик в одной транзакции."""
        async with self.session_maker() as session, session.begin():
            inserted = await session.execute(
                pg_insert(self.table)
                .values(consumer=self.consumer, event_id=event_id)
                .on_conflict_do_nothing()
                .returning(self.table.c.event_id)
            )
            if inserted.first() is None:
                DUPLICATES.labels(consumer=self.consumer).inc()
                return Outcome.DUPLICATE
            await handler(session, json.loads(message.value))
        return Outcome.PROCESSED

    async def _dead_letter(self, message: ConsumedMessage, exc: BaseException, attempts: int) -> None:
        """Публикует исходное сообщение в `<topic>.dlq` с заголовками ошибки (SYS-04-R27)."""
        headers: dict[str, str] = dict(message.headers)
        headers.update(
            {
                "error": f"{exc}"[:MAX_ERROR_LENGTH],
                "error_type": type(exc).__name__,
                "attempts": str(attempts),
                "consumer": self.consumer,
                "original_topic": message.topic,
                "original_partition": str(message.partition),
                "original_offset": str(message.offset),
                "failed_at": Clock().now().isoformat(),
            }
        )
        dlq_topic = f"{message.topic}.dlq"
        await self.dlq.send(dlq_topic, message.key or "", message.value, headers)
        DLQ_MESSAGES.labels(topic=message.topic, consumer=self.consumer).inc()
        app_logger.error(
            "Kafka consumer: сообщение отправлено в DLQ",
            event_id=message.headers.get("event_id"),
            error_type=type(exc).__name__,
            attempts=attempts,
        )


def idempotent_consumer(consumer: str, table: Table) -> Callable[[Handler], Callable[[KafkaMessage], Awaitable[None]]]:
    """Декоратор подписчика FastStream модуля: inbox, ретраи и DLQ для обработчика (SYS-04-R26, R27).

    Обработчик модуля принимает `(session, body)`: сессию транзакции с записью inbox и тело
    сообщения (конверт события или команды как `dict`); схему события он валидирует сам.
    Сессии берутся из пула процесса, приёмник DLQ — `OutboxSink` из контейнера (регистрирует
    роль `worker`). Исходное сообщение подтверждается после фиксации транзакции или записи в DLQ.

    Args:
        consumer: Имя консьюмера `<module>.<handler>`; совпадает с хвостом `group_id`.
        table: Таблица `processed_events` модуля.

    Returns:
        Декоратор, превращающий обработчик модуля в подписчика `(message: KafkaMessage)`.
    """

    def decorate(handler: Handler) -> Callable[[KafkaMessage], Awaitable[None]]:
        """Оборачивает обработчик; сигнатуру обёртки FastStream разбирает для DI."""

        async def subscriber(message: KafkaMessage) -> None:
            processor = IdempotentConsumer(consumer, table, get_session_maker(), container.resolve(OutboxSink))
            await processor.handle(ConsumedMessage.from_kafka(message), handler)

        subscriber.__name__ = getattr(handler, "__name__", "subscriber")
        subscriber.__qualname__ = getattr(handler, "__qualname__", subscriber.__name__)
        subscriber.__doc__ = handler.__doc__
        return subscriber

    return decorate
