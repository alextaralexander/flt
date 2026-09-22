"""Пример Schema для кэширования."""

from uuid import UUID

from py_main_lib.services.schemas.v1_schemas import SuccessfulResponseV1
from pydantic import BaseModel, Field, field_serializer


class BaseCacheMyEntitySchema(BaseModel):
    """Базовая схема MyEntity."""

    name: str = Field(
        description="Название модели",
        examples=["My Model"],
    )


class CacheMyEntitySchema(BaseCacheMyEntitySchema):
    """Схема `MyEntity`."""

    id: UUID = Field(
        description="ID модели",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )

    @field_serializer("id")
    def serialize_id(self, value: UUID) -> str:
        """Сериализация UUID в строковый формат."""
        return str(value)


class CreateCacheMyEntitySchema(CacheMyEntitySchema):
    """Создание `MyEntity`."""


class UpdateCacheMyEntitySchema(CacheMyEntitySchema):
    """Обновление `MyEntity`."""


class CacheMyEntityResponse(SuccessfulResponseV1):
    """Ответ с сущностью из кэша в стандартном конверте."""

    payload: CacheMyEntitySchema | None = Field(
        description="Сущность из кэша (None, если не найдена).",
    )
