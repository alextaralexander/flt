"""Идемпотентный консьюмер: inbox, ретраи и DLQ (SYS-04-R26, R27)."""

import asyncio
import json
from typing import Any

import pytest
from faststream.kafka import KafkaMessage, TestKafkaBroker
from pydantic import BaseModel
from sqlalchemy import Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import container
from app.core.ids import new_id
from app.core.kafka.broker import create_broker
from app.core.kafka.inbox import ConsumedMessage, IdempotentConsumer, NonRetryableError, Outcome, idempotent_consumer
from app.core.kafka.relay import OutboxSink
from tests.core.kafka.conftest import OUTBOX_SCHEMA


TOPIC = f"flt.{OUTBOX_SCHEMA}.thing_created.v1"


class Payload(BaseModel):
    """Схема тела для проверки ошибок валидации."""

    n: int


class RecordingSink:
    """Приёмник DLQ в памяти теста."""

    def __init__(self) -> None:
        """Пустой журнал."""
        self.sent: list[dict[str, Any]] = []

    async def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        """Запоминает сообщение DLQ."""
        self.sent.append({"topic": topic, "key": key, "value": value, "headers": headers})


def _message(event_id: str | None = None, body: dict[str, Any] | None = None) -> ConsumedMessage:
    event_id = event_id or str(new_id())
    return ConsumedMessage(
        topic=TOPIC,
        partition=0,
        offset=7,
        key="agg-1",
        value=json.dumps(body if body is not None else {"payload": {"n": 1}}).encode(),
        headers={"event_id": event_id, "request_id": str(new_id()), "event_type": f"{OUTBOX_SCHEMA}.thing_created"},
    )


def _consumer(inbox: Table, maker: async_sessionmaker[AsyncSession], sink: RecordingSink) -> IdempotentConsumer:
    delays: list[float] = []

    async def no_sleep(seconds: float) -> None:
        delays.append(seconds)

    consumer = IdempotentConsumer("core_outbox_test.handle", inbox, maker, sink, sleep=no_sleep)
    consumer.recorded_delays = delays  # type: ignore[attr-defined]
    return consumer


async def _count(maker: async_sessionmaker[AsyncSession], table: Table) -> int:
    async with maker() as session:
        return int(await session.scalar(select(func.count()).select_from(table)) or 0)


@pytest.mark.req("SYS-04-R26")
async def test_duplicate_delivery_is_processed_once(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Повторная доставка того же `event_id` не вызывает обработчик и не меняет данные."""
    # - Arrange -
    calls: list[dict[str, Any]] = []

    async def handler(session: AsyncSession, body: dict[str, Any]) -> None:
        calls.append(body)

    consumer = _consumer(inbox, session_maker, RecordingSink())
    message = _message()

    # - Act -
    first = await consumer.handle(message, handler)
    second = await consumer.handle(message, handler)

    # - Assert -
    assert (first, second) == (Outcome.PROCESSED, Outcome.DUPLICATE)
    assert len(calls) == 1
    assert await _count(session_maker, inbox) == 1


@pytest.mark.req("SYS-04-R26")
async def test_two_instances_process_same_event_once(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Одно сообщение, доставленное на два «инстанса» одновременно, обрабатывается один раз."""
    calls: list[int] = []

    async def handler(session: AsyncSession, body: dict[str, Any]) -> None:
        calls.append(1)
        await asyncio.sleep(0.05)

    message = _message()
    first, second = (_consumer(inbox, session_maker, RecordingSink()) for _ in range(2))

    outcomes = await asyncio.gather(first.handle(message, handler), second.handle(message, handler))

    assert sorted(outcomes) == sorted([Outcome.PROCESSED, Outcome.DUPLICATE])
    assert len(calls) == 1


@pytest.mark.req("SYS-04-R26")
async def test_handler_changes_and_inbox_share_transaction(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Ошибка обработчика откатывает и его изменения, и запись inbox; успешный повтор фиксирует их вместе."""
    # - Arrange -
    attempts = 0

    async def flaky(session: AsyncSession, body: dict[str, Any]) -> None:
        nonlocal attempts
        attempts += 1
        await session.execute(insert(inbox).values(consumer="side_effect", event_id=new_id()))
        if attempts < 3:
            raise ConnectionError("temporary")

    consumer = _consumer(inbox, session_maker, RecordingSink())

    # - Act -
    outcome = await consumer.handle(_message(), flaky)

    # - Assert -
    assert outcome is Outcome.PROCESSED
    assert attempts == 3
    assert consumer.recorded_delays == [1, 5]  # type: ignore[attr-defined]
    assert await _count(session_maker, inbox) == 2


@pytest.mark.req("SYS-04-R27")
async def test_exhausted_retries_go_to_dlq_with_headers(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """После 4 попыток с задержками 1, 5, 25 с сообщение уходит в `<topic>.dlq` с заголовками ошибки."""

    # - Arrange -
    async def failing(session: AsyncSession, body: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    sink = RecordingSink()
    consumer = _consumer(inbox, session_maker, sink)
    message = _message()

    # - Act -
    outcome = await consumer.handle(message, failing)

    # - Assert -
    assert outcome is Outcome.DEAD_LETTERED
    assert consumer.recorded_delays == [1, 5, 25]  # type: ignore[attr-defined]
    dlq = sink.sent[0]
    assert dlq["topic"] == f"{TOPIC}.dlq"
    assert dlq["key"] == "agg-1"
    assert dlq["value"] == message.value
    headers = dlq["headers"]
    assert headers["event_id"] == message.headers["event_id"]
    assert headers["error_type"] == "RuntimeError"
    assert "boom" in headers["error"]
    assert headers["attempts"] == "4"
    assert headers["consumer"] == "core_outbox_test.handle"
    assert headers["original_topic"] == TOPIC
    assert headers["original_partition"] == "0"
    assert headers["original_offset"] == "7"
    assert "failed_at" in headers
    assert await _count(session_maker, inbox) == 0


@pytest.mark.req("SYS-04-R27")
@pytest.mark.parametrize("error", ["non_retryable", "validation"])
async def test_non_retryable_and_validation_errors_skip_retries(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession], error: str
) -> None:
    """`NonRetryableError` и ошибка валидации — сразу в DLQ, без задержек."""

    # - Arrange -
    async def handler(session: AsyncSession, body: dict[str, Any]) -> None:
        if error == "validation":
            Payload.model_validate(body["payload"])
        raise NonRetryableError("bad command")

    sink = RecordingSink()
    consumer = _consumer(inbox, session_maker, sink)

    # - Act -
    outcome = await consumer.handle(_message(body={"payload": {"n": "x"}}), handler)

    # - Assert -
    assert outcome is Outcome.DEAD_LETTERED
    assert consumer.recorded_delays == []  # type: ignore[attr-defined]
    assert sink.sent[0]["headers"]["attempts"] == "1"


@pytest.mark.req("SYS-04-R27")
async def test_message_without_event_id_goes_to_dlq(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Сообщение без заголовка `event_id` нельзя дедуплицировать — сразу в DLQ."""
    sink = RecordingSink()
    message = _message()
    message.headers.pop("event_id")

    async def handler(session: AsyncSession, body: dict[str, Any]) -> None:
        raise AssertionError("не должен вызываться")

    outcome = await _consumer(inbox, session_maker, sink).handle(message, handler)

    assert outcome is Outcome.DEAD_LETTERED
    assert sink.sent[0]["headers"]["error_type"] == "MissingEventIdError"


@pytest.mark.req("SYS-04-R26")
async def test_consumed_message_from_kafka_subscriber(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """`ConsumedMessage.from_kafka` собирает топик, ключ, тело и заголовки из сообщения FastStream."""
    broker = create_broker()
    collected: list[ConsumedMessage] = []

    @broker.subscriber(TOPIC)
    async def subscriber(message: KafkaMessage) -> None:
        collected.append(ConsumedMessage.from_kafka(message))

    async with TestKafkaBroker(broker):
        await broker.publish(b'{"payload": {"n": 1}}', TOPIC, key=b"agg-1", headers={"event_id": "e1"})

    consumed = collected[0]
    assert (consumed.topic, consumed.key, consumed.headers["event_id"]) == (TOPIC, "agg-1", "e1")
    assert json.loads(consumed.value) == {"payload": {"n": 1}}


@pytest.mark.req("SYS-04-R26")
async def test_decorated_subscriber_processes_redelivery_once(
    inbox: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """`@idempotent_consumer` поверх подписчика FastStream: повторная доставка того же `event_id` — один вызов."""
    # - Arrange -
    broker = create_broker()
    calls: list[dict[str, Any]] = []
    sink = RecordingSink()

    @broker.subscriber(TOPIC, group_id=f"flt.{OUTBOX_SCHEMA}.handle")
    @idempotent_consumer("core_outbox_test.handle", inbox)
    async def handle(session: AsyncSession, body: dict[str, Any]) -> None:
        """Обработчик модуля."""
        calls.append(body)

    headers = {"event_id": str(new_id()), "request_id": str(new_id())}

    # - Act -
    with container.override(OutboxSink, sink):
        async with TestKafkaBroker(broker):
            for _ in range(2):
                await broker.publish(b'{"payload": {"n": 1}}', TOPIC, key=b"agg-1", headers=headers)

    # - Assert -
    assert calls == [{"payload": {"n": 1}}]
    assert sink.sent == []
