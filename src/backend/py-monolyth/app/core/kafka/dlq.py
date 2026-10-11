"""Разбор dead letter topic: просмотр и повторная обработка (ADR-004; SYS-04-R28).

`list_dlq(topic)` читает `<topic>.dlq` с начала и возвращает сводку сообщений, `replay_dlq`
публикует выбранные сообщения обратно в `<topic>` с исходными заголовками и дополнительными
`replayed_from`, `replay_count` (+1), `replayed_at`. Сообщение, повторённое больше 3 раз, без
`force` не возвращается. Команды запускает администратор вручную: `python -m app dlq list|replay`.
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient

from app.core.kafka.inbox import ConsumedMessage
from app.core.logging.context import app_logger
from app.core.time import Clock
from configs.kafka_config import kafka_settings


MAX_REPLAYS = 3
METADATA_ATTEMPTS = 30
LIST_FIELDS = ("event_id", "event_type", "consumer", "error_type", "failed_at")


class DlqReplayLimitError(RuntimeError):
    """Сообщение уже повторяли больше `MAX_REPLAYS` раз; нужен явный `force`."""


async def _partitions(topic: str) -> list[int]:
    """Номера партиций топика по метаданным контроллера (пусто, если топика нет)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        # Метаданные только что созданного топика доходят не сразу: несколько попыток.
        for _ in range(METADATA_ATTEMPTS):
            described = await admin.describe_topics([topic])
            numbers = [item["partition"] for entry in described for item in entry.get("partitions", [])]
            if numbers:
                return sorted(numbers)
            await asyncio.sleep(0.1)
        return []
    finally:
        await admin.close()


async def read_topic(topic: str) -> list[ConsumedMessage]:
    """Все сообщения топика от начала до текущего конца (без группы и коммита смещений)."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS, enable_auto_commit=False, group_id=None
    )
    await consumer.start()
    try:
        partitions = [TopicPartition(topic, number) for number in await _partitions(topic)]
        if not partitions:
            return []
        consumer.assign(partitions)
        await consumer.seek_to_beginning(*partitions)
        end_offsets = await consumer.end_offsets(partitions)
        messages: list[ConsumedMessage] = []
        remaining = {tp for tp in partitions if end_offsets[tp] > 0}
        while remaining:
            batch = await consumer.getmany(*remaining, timeout_ms=1000)
            for tp, records in batch.items():
                for record in records:
                    messages.append(
                        ConsumedMessage(
                            topic=record.topic,
                            partition=record.partition,
                            offset=record.offset,
                            key=record.key.decode() if record.key else None,
                            value=record.value or b"",
                            headers={name: value.decode() for name, value in record.headers},
                        )
                    )
                    if record.offset + 1 >= end_offsets[tp]:
                        remaining.discard(tp)
        return sorted(messages, key=lambda message: (message.partition, message.offset))
    finally:
        await consumer.stop()


def _selected(
    messages: Sequence[ConsumedMessage], event_ids: Sequence[str] | None, consumer: str | None
) -> list[ConsumedMessage]:
    """Фильтр сообщений DLQ по `event_id` и консьюмеру."""
    return [
        message
        for message in messages
        if (not event_ids or message.headers.get("event_id") in event_ids)
        and (consumer is None or message.headers.get("consumer") == consumer)
    ]


async def list_dlq(topic: str, *, since: datetime | None = None) -> list[dict[str, Any]]:
    """Сводка сообщений `<topic>.dlq`: `event_id`, `event_type`, `consumer`, `error_type`, `failed_at`."""
    entries = []
    for message in await read_topic(f"{topic}.dlq"):
        failed_at = message.headers.get("failed_at")
        if since is not None and failed_at and datetime.fromisoformat(failed_at) < since:
            continue
        entries.append({field: message.headers.get(field) for field in LIST_FIELDS})
    return entries


async def replay_dlq(
    topic: str,
    *,
    event_ids: Sequence[str] | None = None,
    consumer: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Возвращает выбранные сообщения `<topic>.dlq` в `<topic>`; результат — их `event_id`.

    Raises:
        DlqReplayLimitError: Среди выбранных есть сообщение с `replay_count > 3`, а `force` не задан.
    """
    dlq = f"{topic}.dlq"
    selected = _selected(await read_topic(dlq), event_ids, consumer)
    over_limit = [m.headers.get("event_id") for m in selected if int(m.headers.get("replay_count", "0")) > MAX_REPLAYS]
    if over_limit and not force:
        raise DlqReplayLimitError(f"Сообщения повторяли больше {MAX_REPLAYS} раз: {over_limit}; нужен --force.")
    replayed = [message.headers.get("event_id", "") for message in selected]
    if dry_run or not selected:
        return replayed

    producer = AIOKafkaProducer(
        bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS, acks="all", enable_idempotence=True
    )
    await producer.start()
    try:
        for message in selected:
            headers = dict(message.headers)
            headers["replayed_from"] = dlq
            headers["replay_count"] = str(int(headers.get("replay_count", "0")) + 1)
            headers["replayed_at"] = Clock().now().isoformat()
            await producer.send_and_wait(
                topic,
                message.value,
                key=message.key.encode() if message.key else None,
                headers=[(name, value.encode()) for name, value in headers.items()],
            )
    finally:
        await producer.stop()
    app_logger.info("DLQ: сообщения возвращены в топик", topic=topic, count=len(selected))
    return replayed
