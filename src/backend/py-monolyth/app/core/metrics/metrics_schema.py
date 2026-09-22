"""Pydantic-схемы ответов сервисных endpoint-ов (health/ready/info/metrics)."""

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


class SystemMetricsSchema(BaseModel):
    """Схема системных метрик."""

    cpu_usage_percent: float = Field(
        description="Процент использования CPU",
    )
    memory_usage_percent: float = Field(
        description="Процент использования памяти",
    )
    memory_available_mb: float = Field(
        description="Доступная память в MB",
    )
    memory_total_mb: float = Field(
        description="Общая память в MB",
    )

    model_config = ConfigDict(from_attributes=True)


class ServiceInfoSchema(BaseModel):
    """Схема информации о сервисе."""

    version: str = Field(
        description="Версия приложения",
    )
    git_commit: str = Field(
        description="Git commit hash",
    )
    build_time: str = Field(
        description="Время сборки",
    )
    python_version: str = Field(
        description="Версия Python",
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


class SystemMetricsResponse(SuccessfulResponseV1):
    """Ответ с системными метриками."""

    payload: SystemMetricsSchema = Field(
        description="Системные метрики сервиса (CPU, память).",
    )


class ServiceInfoResponse(SuccessfulResponseV1):
    """Ответ с информацией о сервисе."""

    payload: ServiceInfoSchema = Field(
        description="Информация о сервисе (версия, коммит, окружение сборки).",
    )
