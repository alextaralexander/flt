"""Тесты Kafka-консьюмеров (TestKafkaBroker)."""

import pytest
from faststream.kafka import TestKafkaBroker

from app.brokers.kafka.kafka_router import kafka_router
from app.brokers.kafka.schemas.enums import KafkaSubscriberTopics
from app.brokers.kafka.schemas.subscriber_messages.inf_topic_02_schema import (
    InfTopic02Schema,
    PayloadInInfTopic02Schema,
)
from app.brokers.kafka.subscribers import subscriber_to_inf_topic_02


pytestmark = pytest.mark.no_db


class TestKafkaSubscribers:
    """Класс с тестами для проверки работы Kafka Subscribers.

    Структура тестов представляет собой Act-Arrange-Assert. Данный шаблон организации тестов имеет:
    - `# - Arrange`, здесь создаются все необходимые данные, объекты или условия, необходимые для теста.
    - `# - Act -`, здесь выполняется тестируемая операция, их может быть несколько.
    - `# - Assert -`, здесь проверяется, соответствует ли результат ожидаемым значениям.
    - (Дополнительно) `# - Clean -`, здесь удаляем объекты из БД, чтобы не влияли на другие тесты.
    """

    async def test_inf_topic_02(self) -> None:
        """Проверка, что subscriber доступен и подписан на topic `INF_TOPIC_02`."""
        # - Arrange -
        # Сервис-обработчик публикует ответ в исходящий Kafka-топик — тот же TestKafkaBroker.
        async with TestKafkaBroker(kafka_router.broker) as broker:
            payload = PayloadInInfTopic02Schema(second_value="TestValue")
            message_to_send = InfTopic02Schema(payload=payload)

            # - Act -
            await broker.publish(message_to_send, KafkaSubscriberTopics.INF_TOPIC_02)

            # - Assert -
            subscriber_to_inf_topic_02.mock.assert_called_once_with(message_to_send.model_dump(mode="json"))
