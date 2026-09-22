"""Схема шаблонного сообщения Kafka."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from py_main_lib.services.schemas.v1_schemas import MessagesV1
from pydantic import BaseModel, Field


class BaseMessageHeaderSchema(BaseModel):
    """Header сообщения для любого брокера."""

    message_type: str = Field(
        description="Название типа сообщения.",
    )
    message_id: UUID = Field(
        description="Уникальный идентификатор сообщения.",
        default_factory=lambda: uuid4(),
    )
    creation_time: datetime = Field(
        description="Дата создания сообщения.",
        default_factory=lambda: datetime.now(UTC),
    )
    correlation_id: UUID = Field(
        description="Идентификатор, который связывает запрос создания с запросом получения ответа. "
        "Он нужен для идентификации того, для какого запроса пришел ответ. ",
        default_factory=lambda: uuid4(),
    )


class SecurityBaseMessageHeaderSchema(BaseMessageHeaderSchema):
    """Header сообщения вместе с access token для авторизации."""

    access_token: str = Field(
        description="Access Token пользователя для аутентификации.",
    )


class BaseMessageSchema(BaseModel):
    """Базовая модель шаблонного сообщения."""

    header: BaseMessageHeaderSchema = Field(
        description="Служебный заголовок сообщения.",
    )

    payload: Any = Field(
        description="Полезная нагрузка сообщения",
        examples=[{"foo": "bar"}],
    )


class SecurityBaseMessageSchema(BaseModel):
    """Базовая модель шаблонного сообщения с access token для авторизации."""

    header: SecurityBaseMessageHeaderSchema = Field(
        description="Заголовок сообщения с access token.",
    )

    payload: Any = Field(
        description="Полезная нагрузка сообщения",
        examples=[{"foo": "bar"}],
    )


class ErrorMessageHeaderSchema(BaseMessageHeaderSchema):
    """Header для Error Message."""

    message_type: Literal["ERROR"] = Field(
        default="ERROR",
        description="Тип сообщения: всегда ERROR.",
    )


class BrokerErrorResponseV1(BaseModel):
    """Формат ответа, если ошибка произошла внутри сервиса."""

    header: ErrorMessageHeaderSchema = Field(
        default_factory=ErrorMessageHeaderSchema,
        description="Заголовок error-ответа.",
    )
    messages: MessagesV1 = Field(
        description="Сообщения об ошибках (ключ ERROR).",
    )
    payload: Any | None = Field(
        default=None,
        description="Полезная нагрузка (обычно отсутствует).",
    )
