"""Базовая схема заголовка сообщения."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class MessageHeader(BaseModel):
    """Модель заголовка сообщения."""

    message_type: str = Field(description="Название типа сообщения")
    message_id: UUID = Field(description="Уникальный идентификатор сообщения.", default_factory=uuid4)
    creation_time: datetime = Field(
        description="Дата создания сообщения.",
        default_factory=datetime.utcnow,
    )

    @field_validator("creation_time")
    def validate_creation_time_format(cls, v: datetime) -> datetime:
        """Удаление информации о часовом поясе."""
        return v.replace(tzinfo=None)
