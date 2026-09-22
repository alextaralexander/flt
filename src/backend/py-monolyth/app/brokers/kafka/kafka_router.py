"""Kafka broker router.

- Используется для subscribe Kafka Topics.
- Позволяет автоматически генерировать документацию asyncapi.
"""

from faststream.kafka.fastapi import KafkaRouter

from app.brokers.kafka.logger import kafka_logger  # noqa
from app.brokers.kafka.middlewares.exception_middleware import (
    kafka_exception_middleware,
)
from app.brokers.kafka.middlewares.external_exception_middleware import (
    ExternalExceptionMiddleware,
)
from app.core.broker_middlewares import KafkaOpenTelemetryMiddleware
from app.core.telemetry import tracer
from configs.kafka_config import kafka_settings


kafka_router = KafkaRouter(
    kafka_settings.KAFKA_BOOTSTRAP_SERVERS,
    schema_url="/asyncapi/kafka",
    logger=None,  # Если где-то теряются логи, то поставить `kafka_logger`.
    # logger=kafka_logger,
    client_id=kafka_settings.kafka_client_id_new,
    max_request_size=kafka_settings.KAFKA_MAX_REQUEST_SIZE,
    middlewares=[
        KafkaOpenTelemetryMiddleware(tracer=tracer),
        ExternalExceptionMiddleware,
        kafka_exception_middleware,
    ],
)
