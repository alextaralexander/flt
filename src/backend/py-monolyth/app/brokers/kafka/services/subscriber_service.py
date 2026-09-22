"""Сервис, что выполняет бизнес-логику при получении сообщения из Kafka."""

from app.brokers.kafka.kafka_router import kafka_router
from app.brokers.kafka.schemas.enums import KafkaPublisherTopics
from app.brokers.kafka.schemas.publisher_messages.inf_topic_01_schema import (
    InfTopic01Schema,
    PayloadInInfTopic01Schema,
)
from app.brokers.kafka.schemas.subscriber_messages.inf_topic_02_schema import (
    InfTopic02Schema,
)


class KafkaSubscriberService:
    """Сервис для Kafka Subscribers."""

    @staticmethod
    async def run_inf_topic_02_process(inf_topic_02_schema: InfTopic02Schema) -> None:
        """Выполнение бизнес-логики при получении сообщения `InfTopic02`.

        В данном примере создается и отправляется новое сообщение в исходящий Kafka-топик `InfTopic01`.
        """
        payload = PayloadInInfTopic01Schema(first_value=inf_topic_02_schema.payload.second_value)
        inf_topic_01_schema = InfTopic01Schema(payload=payload)
        # Публикуем через брокер роутера: он уже подключён в работающем приложении
        # (async with закрыл бы общее соединение), в тестах подменяется TestKafkaBroker.
        await kafka_router.broker.publish(inf_topic_01_schema, KafkaPublisherTopics.INF_TOPIC_01)
