"""Служебные эндпоинты `/v1/health`, `/v1/ready`, `/v1/metrics` (ADR-010, OQ-62).

Открыты без авторизации: их опрашивают HAProxy, probes и Prometheus; снаружи они
недоступны, так как лежат вне `/api` (ADR-012). `/v1/info` и `/v1/system-metrics`
boilerplate удалены (ADR-010). Readiness по ролям — этап 1 Г.9.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from prometheus_client import CONTENT_TYPE_LATEST

from app.core.metrics.metrics_schema import HealthStatusResponse, ReadinessStatusResponse
from app.core.metrics.metrics_service import MetricsService


router = APIRouter(prefix="/v1", tags=["service"])

MetricsServiceDep = Annotated[MetricsService, Depends()]


@router.get(
    "/metrics",
    status_code=status.HTTP_200_OK,
    summary="Get Prometheus metrics",
    description="Get Prometheus metrics",
    operation_id="get_prometheus_metrics",
)
async def get_metrics(service: MetricsServiceDep) -> Response:
    """Получение метрик Prometheus.

    Returns:
        Метрики в формате Prometheus.
    """
    metrics_data = await service.get_metrics()
    return Response(metrics_data, media_type=CONTENT_TYPE_LATEST)


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
    description="Health check endpoint",
    operation_id="health_check",
)
async def health_check(service: MetricsServiceDep) -> HealthStatusResponse:
    """Проверка доступности сервиса.

    Returns:
        Статус доступности сервиса.
    """
    result = await service.get_health_status()
    return HealthStatusResponse(payload=result)


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness check endpoint",
    description="Readiness check endpoint",
    operation_id="readiness_check",
)
async def ready_check(service: MetricsServiceDep) -> ReadinessStatusResponse:
    """Проверка готовности сервиса к обработке запросов.

    Returns:
        Статус готовности сервиса.
    """
    result = await service.get_readiness_status()
    return ReadinessStatusResponse(payload=result)
