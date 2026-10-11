"""Transactional outbox и relay (SYS-04-R22, R24, R25)."""

import asyncio
import json
from collections.abc import Callable
from typing import Any, ClassVar
from uuid import UUID

import pytest
from faststream.kafka import KafkaMessage, KafkaRouter, TestKafkaBroker
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.dao.caching import ModuleRedis
from app.core.ids import new_id
from app.core.kafka.broker import PRODUCER_SETTINGS, create_broker
from app.core.kafka.envelope import BaseEvent, JobCommand
from app.core.kafka.outbox import OutboxPublisher
from app.core.kafka.relay import BrokerSink, OutboxRelay, OutboxSink
from app.core.modules import ModuleDefinition, ModuleLoadError, ModuleRegistry
from app.main import create_worker_app
from tests.core.kafka.conftest import OUTBOX_SCHEMA
from tests.support.redis_instances import redis_instances  # noqa: F401


pytestmark = pytest.mark.req("SYS-04-R24")

EVENT_TOPIC = f"flt.{OUTBOX_SCHEMA}.thing_created.v1"
JOB_TOPIC = f"flt.{OUTBOX_SCHEMA}.jobs.reindex.v1"


class ThingPayload(BaseModel):
    """Нагрузка тестового события."""

    n: int


class ThingCreated(BaseEvent[ThingPayload]):
    """Тестовое событие модуля `core_outbox_test`."""

    event_type: ClassVar[str] = f"{OUTBOX_SCHEMA}.thing_created"
    event_version: ClassVar[int] = 1
    topic: ClassVar[str] = EVENT_TOPIC
    aggregate_type: ClassVar[str] = "thing"


class RecordingSink:
    """Приёмник relay в памяти теста; может падать на заданном сообщении."""

    def __init__(self, fail_on: int | None = None) -> None:
        """Пустой журнал отправок."""
        self.sent: list[dict[str, Any]] = []
        self.fail_on = fail_on

    async def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        """Запоминает сообщение или падает на `fail_on`-м по счёту."""
        body = json.loads(value)
        if self.fail_on is not None and body["payload"].get("n") == self.fail_on:
            self.fail_on = None
            raise ConnectionError("broker down")
        self.sent.append({"topic": topic, "key": key, "body": body, "headers": headers})


async def _publish(maker: async_sessionmaker[AsyncSession], outbox: Table, aggregate_id: UUID, *numbers: int) -> None:
    async with maker() as session, session.begin():
        publisher = OutboxPublisher(outbox)
        for n in numbers:
            await publisher.publish(session, ThingCreated(payload=ThingPayload(n=n)), aggregate_id=aggregate_id)


async def _unpublished(maker: async_sessionmaker[AsyncSession], outbox: Table) -> int:
    async with maker() as session:
        return int(await session.scalar(select(func.count()).where(outbox.c.published_at.is_(None))) or 0)


async def test_publish_is_atomic_with_transaction(
    outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Запись в outbox откатывается вместе с транзакцией данных."""
    # - Act -
    async with session_maker() as session, session.begin():
        await OutboxPublisher(outbox).publish(session, ThingCreated(payload=ThingPayload(n=1)), aggregate_id=new_id())
        await session.rollback()

    # - Assert -
    assert await _unpublished(session_maker, outbox) == 0


@pytest.mark.req("SYS-04-R22")
async def test_relay_publishes_with_key_headers_and_marks_row(
    outbox: Table, session_maker: async_sessionmaker[AsyncSession], raw_test_redis: Redis
) -> None:
    """Relay публикует конверт с ключом `aggregate_id` и заголовками SYS-04-R22 и отмечает строку."""
    # - Arrange -
    aggregate_id = new_id()
    await _publish(session_maker, outbox, aggregate_id, 1)
    sink = RecordingSink()
    relay = OutboxRelay(OUTBOX_SCHEMA, outbox, session_maker, sink, ModuleRedis("shared_kernel", client=raw_test_redis))

    # - Act -
    published = await relay.run_once()

    # - Assert -
    assert published == 1
    message = sink.sent[0]
    assert message["topic"] == EVENT_TOPIC
    assert message["key"] == str(aggregate_id)
    assert message["body"]["event_type"] == f"{OUTBOX_SCHEMA}.thing_created"
    assert message["body"]["aggregate_id"] == str(aggregate_id)
    headers = message["headers"]
    assert headers["event_id"] == message["body"]["event_id"]
    assert headers["event_type"] == f"{OUTBOX_SCHEMA}.thing_created"
    assert headers["event_version"] == "1"
    assert headers["producer"] == OUTBOX_SCHEMA
    assert headers["content_type"] == "application/json"
    assert headers["request_id"] == message["body"]["correlation_id"]
    assert headers["schema"] == f"{OUTBOX_SCHEMA}.ThingCreated"
    assert await _unpublished(session_maker, outbox) == 0
    assert await relay.run_once() == 0


@pytest.mark.req("SYS-04-R25")
async def test_order_per_aggregate_and_retry_on_broker_error(
    outbox: Table, session_maker: async_sessionmaker[AsyncSession], raw_test_redis: Redis
) -> None:
    """Ошибка брокера останавливает проход (порядок агрегата не нарушается); следующий проход повторяет."""
    # - Arrange -
    aggregate_id = new_id()
    await _publish(session_maker, outbox, aggregate_id, 1, 2, 3)
    sink = RecordingSink(fail_on=2)
    relay = OutboxRelay(OUTBOX_SCHEMA, outbox, session_maker, sink, ModuleRedis("shared_kernel", client=raw_test_redis))

    # - Act -
    first = await relay.run_once()
    second = await relay.run_once()

    # - Assert -
    assert (first, second) == (1, 2)
    assert [m["body"]["payload"]["n"] for m in sink.sent] == [1, 2, 3]
    async with session_maker() as session:
        attempts = await session.scalar(select(func.max(outbox.c.attempts)))
        error = await session.scalar(select(outbox.c.last_error).where(outbox.c.attempts > 0))
    assert attempts == 1
    assert error is not None
    assert "broker down" in error


async def test_job_command_uses_job_id_as_key(
    outbox: Table, session_maker: async_sessionmaker[AsyncSession], raw_test_redis: Redis
) -> None:
    """Команда задания идёт в топик заданий модуля с ключом `job_id` (SYS-04-R22, R29)."""
    # - Arrange -
    job_id = new_id()
    async with session_maker() as session, session.begin():
        await OutboxPublisher(outbox).send_command(
            session, JOB_TOPIC, JobCommand[dict[str, Any]](job_id=job_id, kind="reindex", payload={}, attempt=1)
        )
    sink = RecordingSink()

    # - Act -
    await OutboxRelay(
        OUTBOX_SCHEMA, outbox, session_maker, sink, ModuleRedis("shared_kernel", client=raw_test_redis)
    ).run_once()

    # - Assert -
    assert sink.sent[0]["topic"] == JOB_TOPIC
    assert sink.sent[0]["key"] == str(job_id)


async def test_foreign_topic_is_rejected(outbox: Table, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Модуль пишет в outbox только свои топики (SYS-04-R19)."""
    async with session_maker() as session, session.begin():
        with pytest.raises(ValueError, match=r"flt\.other"):
            await OutboxPublisher(outbox).send_command(
                session,
                "flt.other.jobs.reindex.v1",
                JobCommand[dict[str, Any]](job_id=new_id(), kind="reindex", payload={}, attempt=1),
            )


@pytest.mark.req("SYS-04-R25")
async def test_two_relays_on_different_instances_publish_each_event_once(
    outbox: Table,
    session_maker: async_sessionmaker[AsyncSession],
    redis_instances: Callable[[], Redis],  # noqa: F811
) -> None:
    """Два relay с разными клиентами Redis («инстансы»): блокировка даёт один активный, каждое событие — один раз."""
    # - Arrange -
    await _publish(session_maker, outbox, new_id(), *range(1, 31))
    sinks = [RecordingSink(), RecordingSink()]
    relays = [
        OutboxRelay(OUTBOX_SCHEMA, outbox, session_maker, sink, ModuleRedis("shared_kernel", client=client))
        for sink, client in zip(sinks, (redis_instances(), redis_instances()), strict=True)
    ]
    stop = asyncio.Event()

    # - Act -
    tasks = [asyncio.create_task(relay.run(stop)) for relay in relays]
    for _ in range(100):
        if await _unpublished(session_maker, outbox) == 0:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.gather(*tasks)

    # - Assert -
    numbers = [m["body"]["payload"]["n"] for sink in sinks for m in sink.sent]
    assert sorted(numbers) == list(range(1, 31))
    assert sum(1 for sink in sinks if sink.sent) == 1


def test_sink_protocol() -> None:
    """`RecordingSink` реализует протокол приёмника relay."""
    assert isinstance(RecordingSink(), OutboxSink)


@pytest.mark.req("SYS-04-R22")
async def test_broker_sink_publishes_to_kafka_topic() -> None:
    """`BrokerSink` публикует тело, ключ и заголовки в топик брокера (`TestKafkaBroker`)."""
    # - Arrange -
    broker = create_broker()
    received: list[tuple[Any, Any]] = []

    @broker.subscriber(EVENT_TOPIC)
    async def handler(body: dict[str, Any], message: KafkaMessage) -> None:
        received.append((body, message))

    # - Act -
    async with TestKafkaBroker(broker):
        await BrokerSink(broker).send(EVENT_TOPIC, "agg-1", b'{"a": 1}', {"event_type": "x"})

    # - Assert -
    body, message = received[0]
    assert body == {"a": 1}
    assert message.raw_message.key == b"agg-1"
    assert message.headers["event_type"] == "x"


def test_broker_producer_is_idempotent() -> None:
    """Продюсер брокера настроен на `acks=all` и идемпотентность (SYS-04-R24)."""
    assert PRODUCER_SETTINGS == {"acks": "all", "enable_idempotence": True}


@pytest.mark.req("SYS-04-R24")
async def test_worker_lifespan_runs_relay_for_module_outbox(
    outbox: Table, session_maker: async_sessionmaker[AsyncSession], redis_clean: None
) -> None:
    """Роль `worker` запускает relay для модулей с `ModuleDefinition.outbox` и останавливает его при выключении."""
    # - Arrange -
    received: list[dict[str, Any]] = []
    router = KafkaRouter()

    @router.subscriber(EVENT_TOPIC)
    async def collect(body: dict[str, Any]) -> None:
        received.append(body)

    module = ModuleDefinition(name=OUTBOX_SCHEMA, metadata=outbox.metadata, kafka_router=router, outbox=outbox)
    worker = create_worker_app([module], manage_resources=False)
    await _publish(session_maker, outbox, new_id(), 1)

    # - Act -
    async with TestKafkaBroker(worker.brokers[0]), worker.start_lifespan_context():
        for _ in range(100):
            if received:
                break
            await asyncio.sleep(0.05)

    # - Assert -
    assert [body["payload"]["n"] for body in received] == [1]
    assert await _unpublished(session_maker, outbox) == 0


def test_module_outbox_must_live_in_module_schema(outbox: Table) -> None:
    """Таблица outbox модуля лежит в схеме модуля."""
    with pytest.raises(ModuleLoadError, match="outbox"):
        ModuleRegistry.build([ModuleDefinition(name="other", metadata=outbox.metadata, outbox=outbox)])
