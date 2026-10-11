"""Сервис служебных эндпоинтов: метрики Prometheus, liveness и readiness (ADR-010, раздел 3.4)."""

import contextlib
import time

from prometheus_client import generate_latest

from app.core.metrics.metrics_schema import HealthStatusSchema, ReadinessStatusSchema
from app.core.metrics.readiness import ReadinessProbe, check_redis, health_details


class MetricsService:
    """Собирает сервисные метрики и статусы; проверки readiness роли передаёт приложение."""

    @staticmethod
    async def get_metrics() -> bytes:
        """Метрики Prometheus в текстовом exposition-формате; перед сбором обновляет `flt_redis_up`."""
        # При отказе метрика уже выставлена в 0: сбор метрик от Redis не зависит.
        with contextlib.suppress(Exception):
            await check_redis()
        return generate_latest()

    @staticmethod
    async def get_health_status() -> HealthStatusSchema:
        """Liveness: всегда `healthy`; в `checks` — информационные детали Redis."""
        return HealthStatusSchema(status="healthy", timestamp=time.time(), checks=await health_details())

    @staticmethod
    async def get_readiness_status(probe: ReadinessProbe | None) -> tuple[bool, ReadinessStatusSchema]:
        """Readiness по проверкам роли; без проверок (служебные тесты) — готов.

        Returns:
            Признак готовности и тело ответа.
        """
        if probe is None:
            return True, ReadinessStatusSchema(status="ready", timestamp=time.time())
        result = await probe.run()
        return result.ready, ReadinessStatusSchema(
            status="ready" if result.ready else "not_ready", timestamp=result.timestamp, checks=result.checks
        )
