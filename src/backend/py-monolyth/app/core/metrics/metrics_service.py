"""Сервис сервисных метрик: Prometheus, health/readiness, сведения о сборке."""

import os
import platform
import time

import psutil
from prometheus_client import generate_latest

from app.core.metrics.metrics_schema import (
    HealthStatusSchema,
    ReadinessStatusSchema,
    ServiceInfoSchema,
    SystemMetricsSchema,
)


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

    @staticmethod
    async def get_system_metrics() -> SystemMetricsSchema:
        """CPU и память процесса/хоста (psutil)."""
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()

        return SystemMetricsSchema(
            cpu_usage_percent=cpu_percent,
            memory_usage_percent=memory.percent,
            memory_available_mb=memory.available / (1024 * 1024),
            memory_total_mb=memory.total / (1024 * 1024),
        )

    @staticmethod
    async def get_service_info() -> ServiceInfoSchema:
        """Версия сборки, коммит и версия Python."""
        return ServiceInfoSchema(
            version=os.getenv("APP_VERSION", "1.0.0"),
            git_commit=os.getenv("GIT_COMMIT", "unknown"),
            build_time=os.getenv("BUILD_TIME", "unknown"),
            python_version=platform.python_version(),
        )
