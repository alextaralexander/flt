"""Схема Kafka сообщения из Topic `InfTopic02`."""

from typing import Literal

from pydantic import BaseModel, Field

from app.brokers.template_schema import BaseMessageHeaderSchema, BaseMessageSchema


class InfTopic02HeaderSchema(BaseMessageHeaderSchema):
    """Header для `InfTopic02Schema`."""

    message_type: Literal["InfTopic02.message_type"] = Field(
        description="Название типа сообщения.",
        default="InfTopic02.message_type",  # Обязательно задаем значение по умолчанию.
    )


class PayloadInInfTopic02Schema(BaseModel):
    """Payload для `InfTopic02Schema`."""

    second_value: str = Field(
        description="Some description оf `second_value`.",
    )


class InfTopic02Schema(BaseMessageSchema):
    """Схема сообщения, полученного из topic `InfTopic02`."""

    header: InfTopic02HeaderSchema = Field(
        description="Служебный заголовок сообщения topic `InfTopic02`.",
        default_factory=lambda: InfTopic02HeaderSchema(),
    )
    payload: PayloadInInfTopic02Schema = Field(
        description="Полезная нагрузка сообщения topic `InfTopic02`.",
    )
