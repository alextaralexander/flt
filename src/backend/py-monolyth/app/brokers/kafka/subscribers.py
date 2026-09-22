"""Subscribers для Kafka.

Прослушивают Kafka topics и обрабатывают полученное сообщение.
Сервисы приходят через `Depends()` — как и в HTTP-контроллерах,
их можно подменить в тестах.
"""

from typing import Annotated

from fastapi import Depends

from app.brokers.kafka.kafka_router import kafka_router
from app.brokers.kafka.schemas.enums import KafkaSubscriberTopics
from app.brokers.kafka.schemas.subscriber_messages.inf_topic_02_schema import (
    InfTopic02Schema,
)
from app.brokers.kafka.services.subscriber_service import KafkaSubscriberService
from app.core.logging import bind_broker_log_context
from configs.kafka_config import kafka_settings


@kafka_router.subscriber(
    KafkaSubscriberTopics.INF_TOPIC_02,
    title="INF_TOPIC_02",
    description="Шаблонный входящий Kafka topic.",
    **kafka_settings.subscriber_config.get_subscriber_kwargs(),
)
async def subscriber_to_inf_topic_02(
    inf_topic_02_message: InfTopic02Schema,
    kafka_service: Annotated[KafkaSubscriberService, Depends()],
) -> None:
    """Subscriber для топика INF_TOPIC_02."""
    bind_broker_log_context(inf_topic_02_message)

    await kafka_service.run_inf_topic_02_process(inf_topic_02_message)
