"""Создание топиков Kafka по декларациям модулей — шаг роли `migrate` (ADR-004; SYS-04-R21, R23).

Для каждой `TopicDeclaration` создаются топик и его DLQ `<topic>.dlq` с числом партиций из
декларации, `retention.ms` (DLQ — 30 суток), `cleanup.policy=delete` и `replication.factor`
из настроек стенда (`KAFKA_REPLICATION_FACTOR`: 1 в docker-compose, 3 в Kubernetes). Шаг
идемпотентен: существующие топики не меняются, одновременный запуск двух `migrate` безопасен.
Увеличение партиций существующего топика — отдельная операция `topics apply` (SYS-04-R23).
"""

from collections.abc import Iterable
from datetime import timedelta

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from app.core.kafka.declarations import TopicDeclaration
from app.core.logging.context import app_logger
from configs.kafka_config import kafka_settings


def _new_topic(name: str, partitions: int, retention: timedelta, replication_factor: int) -> NewTopic:
    """Описание нового топика с параметрами SYS-04-R23."""
    return NewTopic(
        name=name,
        num_partitions=partitions,
        replication_factor=replication_factor,
        topic_configs={
            "retention.ms": str(int(retention.total_seconds() * 1000)),
            "cleanup.policy": "delete",
        },
    )


async def apply_topics(declarations: Iterable[TopicDeclaration]) -> list[str]:
    """Создаёт недостающие топики и их DLQ.

    Args:
        declarations: Декларации топиков модулей реестра.

    Returns:
        Имена созданных этим вызовом топиков (уже существующие не входят).
    """
    replication_factor = kafka_settings.KAFKA_REPLICATION_FACTOR
    wanted: dict[str, NewTopic] = {}
    for declaration in declarations:
        wanted[declaration.name] = _new_topic(
            declaration.name, declaration.partitions, declaration.retention, replication_factor
        )
        wanted[declaration.dlq] = _new_topic(
            declaration.dlq, declaration.partitions, declaration.dlq_retention, replication_factor
        )
    if not wanted:
        return []

    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    created: list[str] = []
    try:
        existing = set(await admin.list_topics())
        for name, topic in wanted.items():
            if name in existing:
                continue
            try:
                response = await admin.create_topics([topic])
            except TopicAlreadyExistsError:
                continue
            errors = {error[0]: error[1] for error in getattr(response, "topic_errors", [])}
            if errors.get(name, 0) == 0:
                created.append(name)
            elif errors[name] != TopicAlreadyExistsError.errno:
                raise RuntimeError(f"Не удалось создать топик {name}: код ошибки Kafka {errors[name]}.")
    finally:
        await admin.close()
    app_logger.info("Топики Kafka применены", created=len(created), declared=len(wanted))
    return created
