"""Pydantic-схемы ответов служебных эндпоинтов (health/ready)."""

from py_main_lib.services.schemas.v1_schemas import SuccessfulResponseV1
from pydantic import BaseModel, ConfigDict, Field


class HealthStatusSchema(BaseModel):
    """Схема статуса здоровья сервиса."""

    status: str = Field(
        description="Статус здоровья",
        examples=["healthy"],
    )
    timestamp: float = Field(
        description="Временная метка",
    )

    model_config = ConfigDict(from_attributes=True)


class ReadinessStatusSchema(BaseModel):
    """Схема статуса готовности сервиса."""

    status: str = Field(
        description="Статус готовности",
        examples=["ready"],
    )
    timestamp: float = Field(
        description="Временная метка",
    )

    model_config = ConfigDict(from_attributes=True)


class HealthStatusResponse(SuccessfulResponseV1):
    """Ответ с информацией о здоровье сервиса."""

    payload: HealthStatusSchema = Field(
        description="Данные о состоянии здоровья сервиса.",
    )


class ReadinessStatusResponse(SuccessfulResponseV1):
    """Ответ с информацией о готовности сервиса."""

    payload: ReadinessStatusSchema = Field(
        description="Данные о готовности сервиса принимать запросы.",
    )
