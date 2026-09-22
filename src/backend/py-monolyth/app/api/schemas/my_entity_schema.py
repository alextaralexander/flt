"""Пример Schema."""

from uuid import UUID

from py_main_lib.filter_utils.schemas.filter_schema import FilterResult
from py_main_lib.services.schemas.v1_schemas import SuccessfulResponseV1
from pydantic import BaseModel, ConfigDict, Field, field_serializer


class BaseMyEntitySchema(BaseModel):
    """Базовая схема MyEntity."""

    name: str = Field(
        description="Название модели",
        examples=["My Model"],
    )


class MyEntitySchema(BaseMyEntitySchema):
    """Схема `MyEntity`."""

    id: UUID = Field(
        description="ID модели",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, value: UUID) -> str:
        """Сериализация UUID в строковый формат."""
        return str(value)


class CreateMyEntitySchema(BaseMyEntitySchema):
    """Создание `MyEntity`."""

    model_config = ConfigDict(from_attributes=True)


class UpdateMyEntitySchema(BaseMyEntitySchema):
    """Обновление `MyEntity`."""

    model_config = ConfigDict(from_attributes=True)


class MyEntityResponse(SuccessfulResponseV1):
    """Ответ с одной сущностью `MyEntity` в стандартном конверте."""

    payload: MyEntitySchema = Field(
        description="Найденная/изменённая сущность.",
    )


class MyEntityFilterResult(FilterResult):
    """Страница результатов фильтрации `MyEntity` (+пагинация из FilterResult)."""

    result: list[MyEntitySchema] = Field(
        description="Сущности текущей страницы.",
    )


class FilteredMyEntityResponse(SuccessfulResponseV1):
    """Ответ фильтрации `MyEntity` в стандартном конверте."""

    payload: MyEntityFilterResult = Field(
        description="Результат фильтрации с пагинацией.",
    )
