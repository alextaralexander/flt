"""Создание топиков и DLQ ролью `migrate` по декларациям модулей (SYS-04-R21, R23)."""

import asyncio
from datetime import timedelta

import pytest
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.admin.config_resource import ConfigResource, ConfigResourceType

from app.core.ids import new_id
from app.core.kafka.declarations import TopicDeclaration
from app.core.kafka.topics_admin import apply_topics
from configs.kafka_config import kafka_settings


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-04-R23")]


async def _describe(names: list[str]) -> dict[str, tuple[int, str]]:
    """Число партиций и `retention.ms` топиков."""
    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        # Метаданные только что созданного топика доходят до контроллера не мгновенно.
        partitions: dict[str, int] = {}
        for _ in range(50):
            described = await admin.describe_topics(names)
            partitions = {item["topic"]: len(item["partitions"]) for item in described}
            if all(partitions.get(name) for name in names):
                break
            await asyncio.sleep(0.1)
        configs = await admin.describe_configs([ConfigResource(ConfigResourceType.TOPIC, name) for name in names])
        retention: dict[str, str] = {}
        for response in configs:
            for resource in response.resources:
                name = resource[3]
                values = {entry[0]: entry[1] for entry in resource[4]}
                retention[name] = values["retention.ms"]
        return {name: (partitions[name], retention[name]) for name in names}
    finally:
        await admin.close()


async def test_topics_and_dlq_are_created_idempotently() -> None:
    """Топик и его DLQ создаются с партициями и retention из декларации; повторный и параллельный запуск безопасны."""
    # - Arrange -
    suffix = new_id().hex[:12]
    declaration = TopicDeclaration(name=f"flt.core_topics_test.t{suffix}.v1", partitions=3, retention=timedelta(days=2))

    # - Act -
    created = await apply_topics([declaration])
    again = await asyncio.gather(apply_topics([declaration]), apply_topics([declaration]))

    # - Assert -
    assert set(created) == {declaration.name, declaration.dlq}
    assert again == [[], []]
    described = await _describe([declaration.name, declaration.dlq])
    assert described[declaration.name] == (3, str(int(timedelta(days=2).total_seconds() * 1000)))
    assert described[declaration.dlq] == (3, str(int(timedelta(days=30).total_seconds() * 1000)))
