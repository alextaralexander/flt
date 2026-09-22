"""Publishers для Kafka.

- В коде не используются.
- Нужны только для отображения asyncapi документации.
"""

from app.brokers.kafka.kafka_router import kafka_router
from app.brokers.kafka.schemas.enums import KafkaPublisherTopics
from app.brokers.kafka.schemas.publisher_messages.inf_topic_01_schema import (
    InfTopic01Schema,
)


@kafka_router.publisher(
    KafkaPublisherTopics.INF_TOPIC_01,
    title="INF_TOPIC_01",
    description="Шаблонный исходящий Kafka topic.",
)
async def publish_inf_topic_01_message() -> InfTopic01Schema:
    """Publish Message для топика `INF_TOPIC_01`."""
    raise
