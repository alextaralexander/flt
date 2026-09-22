"""Тесты exception-middleware Kafka-консьюмеров."""

from typing import Any

import pytest
from faststream.kafka import TestKafkaBroker
from pytest_mock import MockerFixture

from app.brokers.kafka.kafka_router import kafka_router
from app.brokers.kafka.schemas.enums import KafkaSubscriberTopics
from app.brokers.kafka.schemas.subscriber_messages.inf_topic_02_schema import (
    InfTopic02Schema,
    PayloadInInfTopic02Schema,
)
from app.brokers.kafka.services.subscriber_service import KafkaSubscriberService
from app.core.exceptions import BaseCustomException


pytestmark = pytest.mark.no_db


class TestKafkaExceptionMiddleware:
    """Класс с тестами для проверки работы Kafka Exception middleware.

    Структура тестов представляет собой Act-Arrange-Assert. Данный шаблон организации тестов имеет:
    - `# - Arrange`, здесь создаются все необходимые данные, объекты или условия, необходимые для теста.
    - `# - Act -`, здесь выполняется тестируемая операция, их может быть несколько.
    - `# - Assert -`, здесь проверяется, соответствует ли результат ожидаемым значениям.
    - (Дополнительно) `# - Clean -`, здесь удаляем объекты из БД, чтобы не влияли на другие тесты.
    """

    async def test_any_exception_handler(self, mocker: MockerFixture) -> None:
        """Проверка, что exception handler перехватил любую ошибку."""

        # - Arrange -
        async def service_method_to_raise_exception(*args: Any, **kwargs: Any) -> None:
            """Вызываем ошибку."""
            raise Exception("Test Exception.")

        mocker.patch.object(KafkaSubscriberService, "run_inf_topic_02_process", service_method_to_raise_exception)

        async with TestKafkaBroker(kafka_router.broker) as broker:
            payload = PayloadInInfTopic02Schema(second_value="TestValue")
            inf_topic_02_schema = InfTopic02Schema(payload=payload)

            # - Act -
            await broker.publish(inf_topic_02_schema.model_dump(), KafkaSubscriberTopics.INF_TOPIC_02)

            # - Assert -
            assert True  # Если не была вызвана ошибка, то тест пройден.

    async def test_base_custom_exception_handler(self, mocker: MockerFixture) -> None:
        """Проверка, что exception handler перехватил `BaseCustomException`."""

        # - Arrange -
        async def service_method_to_raise_exception(*args: Any, **kwargs: Any) -> None:
            """Вызываем ошибку."""
            raise BaseCustomException()

        mocker.patch.object(KafkaSubscriberService, "run_inf_topic_02_process", service_method_to_raise_exception)

        async with TestKafkaBroker(kafka_router.broker) as broker:
            payload = PayloadInInfTopic02Schema(second_value="TestValue")
            message_to_send = InfTopic02Schema(payload=payload)

            # - Act -
            await broker.publish(message_to_send, KafkaSubscriberTopics.INF_TOPIC_02)

            # - Assert -
            assert True  # Если не была вызвана ошибка, то тест пройден.
