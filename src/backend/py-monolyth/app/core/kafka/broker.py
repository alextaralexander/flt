"""Брокер Kafka процесса (FastStream, ADR-004).

Вместо устаревшей интеграции `faststream.kafka.fastapi.KafkaRouter` (ADR-001, раздел 4.2)
брокер — обычный `KafkaBroker`, который поднимает приложение роли `worker`
(`AsgiFastStream`, см. `app.main.create_worker_app`). Модули объявляют свои
`faststream.kafka.KafkaRouter`, брокер включает их по реестру. Объект брокера
создаётся фабрикой: подключение к Kafka происходит только в `broker.start()`
(lifespan), импорт кода побочных эффектов не имеет.
"""

from collections.abc import Sequence

from faststream.kafka import KafkaBroker
from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware

from app.core.modules import ModuleDefinition, module_kafka_routers
from configs.kafka_config import kafka_settings


# Продюсер relay outbox: подтверждение всеми репликами и идемпотентность (SYS-04-R24).
PRODUCER_SETTINGS = {"acks": "all", "enable_idempotence": True}


def create_broker(modules: Sequence[ModuleDefinition] = (), role: str = "worker") -> KafkaBroker:
    """Создаёт брокер Kafka и подключает к нему Kafka-роутеры модулей.

    Args:
        modules: Модули реестра; подключаются роутеры тех, у кого есть `kafka_router`.
        role: Роль процесса — входит в client_id `flt-<role>-<instance_id>` (ADR-004).

    Returns:
        Неподключённый `KafkaBroker` (соединение открывает `broker.start()`).
    """
    broker = KafkaBroker(
        kafka_settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id=kafka_settings.client_id(role),
        max_request_size=kafka_settings.KAFKA_MAX_REQUEST_SIZE,
        acks="all",
        enable_idempotence=True,
        logger=None,
        # Трейсы и метрики сообщений — встроенный middleware FastStream (провайдер OTel — глобальный).
        middlewares=[KafkaTelemetryMiddleware()],
    )
    for router in module_kafka_routers(modules):
        broker.include_router(router)
    return broker
