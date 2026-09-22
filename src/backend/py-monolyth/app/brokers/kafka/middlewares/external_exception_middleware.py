"""Обработчик "сообщений об ошибке" для Kafka Consumer."""

import json
from types import TracebackType
from typing import Any, cast

from aiokafka import ConsumerRecord
from faststream import BaseMiddleware
from faststream.exceptions import AckMessage

from app.brokers.kafka.logger import kafka_logger
from app.brokers.topics_handlers import KAFKA_ERROR_TOPIC_BY_SOURCE


class ExternalExceptionMiddleware(BaseMiddleware):
    """Middleware для обработки "сообщений об ошибке".

    Этот middleware перехватывает входящие сообщения и проверяет, являются ли они ошибочными.
    Если сообщение содержит ошибку, оно логируется и перенаправляется в соответствующий topic,
    после чего помечается как обработанное.
    """

    def _record(self) -> ConsumerRecord:
        """Сырое aiokafka-сообщение; брокер всегда создаёт middleware с сообщением."""
        if self.msg is None:
            raise RuntimeError("ExternalExceptionMiddleware вызван без сообщения.")
        return self.msg

    async def on_receive(self) -> None:
        """Метод вызывается при получении нового сообщения.

        Если сообщение не является ошибочным, оно передаётся дальше в стандартную обработку.
        Если сообщение является ошибочным, оно пересылается в другой topic и помечается как обработанное.
        """
        record = self._record()
        if self.is_potential_error_message():
            json_message = json.loads(record.value)
            if self.is_error_message(json_message):
                await self._forward_error_message(record, json_message)
                raise AckMessage()

        kafka_logger.info(
            "Received message.",
            extra={
                "topic": record.topic,
                # "correlation_id": Todo,
                # "message_id": Todo,
            },
        )
        return await super().on_receive()

    async def _forward_error_message(self, record: ConsumerRecord, json_message: dict[str, Any]) -> None:
        """Пересылает готовое error-сообщение в callback-топик исходного топика.

        Публикуем через брокер роутера (уже подключён; в тестах подменяется
        TestKafkaBroker). Если callback не настроен — только логируем.
        """
        # Локальный импорт: kafka_router сам подключает этот middleware.
        from app.brokers.kafka.kafka_router import kafka_router

        error_topic = KAFKA_ERROR_TOPIC_BY_SOURCE.get(record.topic)
        if error_topic is None:
            kafka_logger.error(
                "Для топика не настроен callback-топик ошибок (KAFKA_ERROR_TOPIC_BY_SOURCE).",
                extra={"topic": record.topic},
            )
            return

        await kafka_router.broker.publish(record.value, error_topic)
        kafka_logger.info(
            f"Received error message. Forwarded to `{error_topic}` topic.",
            extra={
                "topic": record.topic,
                "message_mnemocode": self.get_error_mnemocode(json_message),
                "correlation_id": self.get_correlation_id(json_message),
                "message_id": self.get_message_id(json_message),
            },
        )

    async def after_processed(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        """Логирует факт завершения обработки сообщения."""
        await super().after_processed(exc_type, exc_val, exc_tb)
        kafka_logger.info(
            "Processed message.",
            extra={
                "topic": self._record().topic,
                # "correlation_id": Todo,
                # "message_id": Todo,
            },
        )

    def is_potential_error_message(self) -> bool:
        """Проверяет, является ли сообщение потенциально ошибочным.

        Данная проверка нужна чтобы не делать json.loads() два раза, так как
        после отрабатывания этого middleware(если сообщение не об ошибке)
        faststream сам сделает json.loads().
        """
        return bool(self._record().value.find(b"ERROR") != -1)

    @staticmethod
    def is_error_message(json_message: dict[str, Any]) -> bool:
        """Определяет, является ли сообщение действительно ошибочным.

        Сообщение считается ошибочным, если в поле `messages["ERROR"]` есть хотя бы один элемент.
        """
        return len(json_message["messages"]["ERROR"]) > 0

    @staticmethod
    def get_error_mnemocode(json_message: dict[str, Any]) -> str:
        """Получает мнемокод ошибки из сообщения.

        Берётся первая ошибка, и из неё извлекается поле `message_mnemo_code`.
        """
        return cast("str", json_message["messages"]["ERROR"][0].get("message_mnemo_code"))

    @staticmethod
    def get_correlation_id(json_message: dict[str, Any]) -> str:
        """Получает correlation_id из сообщения."""
        return cast("str", json_message["header"].get("correlation_id"))

    @staticmethod
    def get_message_id(json_message: dict[str, Any]) -> str:
        """Получает message_id из сообщения."""
        return cast("str", json_message["header"].get("message_id"))
