"""Обработчики ошибок Kafka-консьюмеров.

Оба хендлера собирают единый конверт (`BrokerErrorResponseV1`) через
`_publish_error_response` и публикуют его в callback-топик исходного
сообщения (маппинг — `KAFKA_ERROR_TOPIC_BY_SOURCE`).
"""

from typing import Any, cast

from aiokafka import ConsumerRecord
from faststream import Context, ExceptionMiddleware
from faststream.kafka.fastapi import KafkaMessage
from py_main_lib.services.schemas.v1_schemas import MessagesV1

from app.brokers.kafka.logger import kafka_logger
from app.brokers.template_schema import BaseMessageSchema, BrokerErrorResponseV1
from app.brokers.topics_handlers import KAFKA_ERROR_TOPIC_BY_SOURCE
from app.core.exceptions import BaseCustomException
from configs.settings import settings


kafka_exception_middleware = ExceptionMiddleware()


async def _publish_error_response(message: KafkaMessage, mnemo_code: str, parameters: dict[str, Any]) -> None:
    """Собирает конверт ошибки и публикует его в callback-топик исходного топика.

    Публикуем через брокер роутера: он уже подключён в работающем приложении
    и подменяется TestKafkaBroker в тестах. Если callback для топика не
    настроен — логируем и выходим, не роняя error-handler.
    """
    # Локальный импорт: kafka_router сам подключает этот модуль как middleware.
    from app.brokers.kafka.kafka_router import kafka_router

    record = cast("ConsumerRecord", message.raw_message)
    error_topic = KAFKA_ERROR_TOPIC_BY_SOURCE.get(record.topic)
    if error_topic is None:
        kafka_logger.error(
            "Для топика не настроен callback-топик ошибок (KAFKA_ERROR_TOPIC_BY_SOURCE).",
            extra={"topic": record.topic},
        )
        return

    base_message = BaseMessageSchema(**cast("dict[str, Any]", await message.decode()))
    error_response = BrokerErrorResponseV1(
        messages=MessagesV1(
            ERROR=[
                {
                    "message_mnemo_code": mnemo_code,
                    "parameters": parameters,
                    "correlation_id": base_message.header.correlation_id,
                },
            ]
        )
    )

    await kafka_router.broker.publish(error_response, error_topic)
    kafka_logger.info(
        "Published message.",
        extra={
            "topic": error_topic,
            "message_id": str(error_response.header.message_id),
            "correlation_id": str(error_response.header.correlation_id),
        },
    )


@kafka_exception_middleware.add_handler(BaseCustomException)
async def base_exception_handler(
    exc: BaseCustomException,
    message: KafkaMessage = Context(),
) -> None:
    """Доменная ошибка: мнемокод и параметры уходят в callback-топик."""
    await _publish_error_response(message, exc.message_mnemo_code, dict(exc.parameters))


@kafka_exception_middleware.add_handler(Exception)
async def any_exception_handler(
    exc: Exception,
    message: KafkaMessage = Context(),
) -> None:
    """Непредвиденная ошибка: детали отдаём наружу только в DEBUG_MODE."""
    kafka_logger.exception("Unhandled exception while processing message.")
    parameters = {"ERROR": str(exc) if settings.DEBUG_MODE else None}
    await _publish_error_response(message, "UNHANDLED_EXCEPTION", parameters)
