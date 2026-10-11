"""Базовые схемы Kafka-сообщений модулей, которые генерирует скаффолдер.

Конверт доменного события и команда задания — `app.core.kafka.envelope` (`EventEnvelope`,
`BaseEvent`, `JobCommand`, SYS-04-R20, R29); `OutboxPublisher` — следующий шаг этапа 1 Г.4.
До перевода скаффолдера на `BaseEvent` сгенерированные схемы наследуют эти базовые классы.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class BaseMessageHeaderSchema(BaseModel):
    """Служебный заголовок сообщения."""

    message_type: str = Field(
        description="Название типа сообщения.",
    )
    message_id: UUID = Field(
        description="Уникальный идентификатор сообщения.",
        default_factory=uuid4,
    )
    creation_time: datetime = Field(
        description="Дата создания сообщения (UTC).",
        default_factory=lambda: datetime.now(UTC),
    )
    correlation_id: UUID = Field(
        description="Идентификатор, связывающий сообщения одной цепочки обработки.",
        default_factory=uuid4,
    )


class BaseMessageSchema(BaseModel):
    """Базовая модель сообщения: заголовок и полезная нагрузка."""

    header: BaseMessageHeaderSchema = Field(
        description="Служебный заголовок сообщения.",
    )

    payload: Any = Field(
        description="Полезная нагрузка сообщения",
        examples=[{"foo": "bar"}],
    )
