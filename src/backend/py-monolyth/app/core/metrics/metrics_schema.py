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
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Информационные детали зависимостей (`redis`); на код ответа не влияют.",
        examples=[{"redis": "ok"}],
    )

    model_config = ConfigDict(from_attributes=True)


class ReadinessStatusSchema(BaseModel):
    """Схема статуса готовности сервиса."""

    status: str = Field(
        description="Статус готовности",
        examples=["ready", "not_ready"],
    )
    timestamp: float = Field(
        description="Временная метка",
    )
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Проверки роли: `ok` или ошибка (`postgres`, `kafka`).",
        examples=[{"postgres": "ok"}],
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
