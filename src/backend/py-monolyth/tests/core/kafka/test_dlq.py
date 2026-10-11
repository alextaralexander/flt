"""Просмотр и повторная обработка dead letter topic (SYS-04-R28)."""

import pytest
from aiokafka import AIOKafkaProducer

from app.core.ids import new_id
from app.core.kafka.declarations import TopicDeclaration
from app.core.kafka.dlq import DlqReplayLimitError, list_dlq, read_topic, replay_dlq
from app.core.kafka.topics_admin import apply_topics
from configs.kafka_config import kafka_settings


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-04-R28")]


async def _topic_with_dlq(*replay_counts: int) -> tuple[TopicDeclaration, list[str]]:
    """Новый топик и его DLQ с сообщениями; возвращает `event_id` сообщений DLQ."""
    declaration = TopicDeclaration(name=f"flt.core_dlq_test.t{new_id().hex[:12]}.v1", partitions=1)
    await apply_topics([declaration])
    producer = AIOKafkaProducer(bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    event_ids = []
    try:
        for count in replay_counts:
            event_id = str(new_id())
            event_ids.append(event_id)
            headers = {
                "event_id": event_id,
                "event_type": "core_dlq_test.t",
                "consumer": "core_dlq_test.handle",
                "error_type": "RuntimeError",
                "failed_at": "2026-10-11T00:00:00+00:00",
            }
            if count:
                headers["replay_count"] = str(count)
            await producer.send_and_wait(
                declaration.dlq,
                b'{"payload": {}}',
                key=b"agg",
                headers=[(name, value.encode()) for name, value in headers.items()],
            )
    finally:
        await producer.stop()
    return declaration, event_ids


async def test_list_shows_dlq_messages() -> None:
    """`dlq list` показывает `event_id`, `event_type`, `consumer`, `error_type`, `failed_at`."""
    declaration, event_ids = await _topic_with_dlq(0, 0)

    entries = await list_dlq(declaration.name)

    assert [entry["event_id"] for entry in entries] == event_ids
    assert entries[0]["consumer"] == "core_dlq_test.handle"
    assert entries[0]["error_type"] == "RuntimeError"


async def test_replay_selected_message_back_to_topic() -> None:
    """`dlq replay --event-id` возвращает сообщение в исходный топик с `replayed_from` и `replay_count`."""
    declaration, event_ids = await _topic_with_dlq(0, 0)

    replayed = await replay_dlq(declaration.name, event_ids=[event_ids[1]])
    dry = await replay_dlq(declaration.name, event_ids=[event_ids[0]], dry_run=True)

    messages = await read_topic(declaration.name)
    assert replayed == [event_ids[1]]
    assert dry == [event_ids[0]]
    assert [message.headers["event_id"] for message in messages] == [event_ids[1]]
    assert messages[0].headers["replayed_from"] == declaration.dlq
    assert messages[0].headers["replay_count"] == "1"
    assert messages[0].key == "agg"


async def test_replay_limit_requires_force() -> None:
    """Сообщение, повторённое больше 3 раз, без `--force` не возвращается."""
    declaration, event_ids = await _topic_with_dlq(4)

    with pytest.raises(DlqReplayLimitError):
        await replay_dlq(declaration.name)
    assert await replay_dlq(declaration.name, force=True) == event_ids
