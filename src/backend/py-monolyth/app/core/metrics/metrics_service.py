"""Сервис служебных эндпоинтов: метрики Prometheus, liveness и readiness."""

import time

from prometheus_client import generate_latest

from app.core.metrics.metrics_schema import HealthStatusSchema, ReadinessStatusSchema


class MetricsService:
    """Собирает сервисные метрики и статусы (stateless, без зависимостей)."""

    @staticmethod
    async def get_metrics() -> bytes:
        """Метрики Prometheus в текстовом exposition-формате."""
        return generate_latest()

    @staticmethod
    async def get_health_status() -> HealthStatusSchema:
        """Статус живости процесса (liveness)."""
        return HealthStatusSchema(
            status="healthy",
            timestamp=time.time(),
        )

    @staticmethod
    async def get_readiness_status() -> ReadinessStatusSchema:
        """Готовность принимать трафик (readiness)."""
        return ReadinessStatusSchema(
            status="ready",
            timestamp=time.time(),
        )
