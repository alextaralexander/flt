"""Контроллер для сервисных метрик и health-check endpoint'ов.

`/health`, `/ready`, `/metrics` открыты (их опрашивают probes и Prometheus);
`/info` и `/system-metrics` раскрывают сведения о сборке и хосте — закрыты
permissions (см. `MetricsPermissions`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, Security, status
from prometheus_client import CONTENT_TYPE_LATEST

from app.core.metrics.metrics_schema import (
    HealthStatusResponse,
    ReadinessStatusResponse,
    ServiceInfoResponse,
    SystemMetricsResponse,
)
from app.core.metrics.metrics_service import MetricsService
from app.core.security.permissions import MetricsPermissions
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user


router = APIRouter(tags=["metrics"])

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


@router.get(
    "/info",
    status_code=status.HTTP_200_OK,
    summary="Service information",
    description="Service information",
    operation_id="get_service_info",
)
async def service_info(
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MetricsPermissions.GET_SERVICE_INFO])),
    ],
    service: MetricsServiceDep,
) -> ServiceInfoResponse:
    """Получение информации о сервисе (версия сборки, коммит) — требует permission.

    Returns:
        Информация о сервисе.
    """
    result = await service.get_service_info()
    return ServiceInfoResponse(payload=result)


@router.get(
    "/system-metrics",
    status_code=status.HTTP_200_OK,
    summary="System metrics",
    description="System metrics",
    operation_id="get_system_metrics",
)
async def system_metrics(
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MetricsPermissions.GET_SYSTEM_METRICS])),
    ],
    service: MetricsServiceDep,
) -> SystemMetricsResponse:
    """Получение системных метрик (CPU/память хоста) — требует permission.

    Returns:
        Системные метрики.
    """
    result = await service.get_system_metrics()
    return SystemMetricsResponse(payload=result)
