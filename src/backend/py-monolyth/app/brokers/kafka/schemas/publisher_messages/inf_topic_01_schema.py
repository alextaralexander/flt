"""Схема Kafka сообщения в Topic `InfTopic01`."""

from typing import Literal

from pydantic import BaseModel, Field

from app.brokers.template_schema import BaseMessageHeaderSchema, BaseMessageSchema


class InfTopic01HeaderSchema(BaseMessageHeaderSchema):
    """Header для `InfTopic01Schema`."""

    message_type: Literal["InfTopic01.message_type"] = Field(
        description="Название типа сообщения.",
        default="InfTopic01.message_type",  # Обязательно задаем значение по умолчанию.
    )


class PayloadInInfTopic01Schema(BaseModel):
    """Payload для `InfTopic01Schema`."""

    first_value: str = Field(
        description="Some description оf `first_value`.",
    )


class InfTopic01Schema(BaseMessageSchema):
    """Схема сообщения для отправки в topic `InfTopic01`."""

    header: InfTopic01HeaderSchema = Field(
        description="Служебный заголовок сообщения topic `InfTopic01`.",
        default_factory=lambda: InfTopic01HeaderSchema(),
    )
    payload: PayloadInInfTopic01Schema = Field(
        description="Полезная нагрузка сообщения topic `InfTopic01`.",
    )
