"""Этот пакет содержит контроллеры (router'ы) для обработки HTTP-запросов в FastAPI-приложении.
Контроллеры связывают endpoint'ы API с бизнес-логикой, вызывая соответствующие сервисы.
"""

from fastapi import APIRouter

from app.api.controllers.caching_controllers.cache_entity_controller import (
    router as cache_my_entity_router,
)
from app.api.controllers.my_entity_controller import router as my_entity_router
from app.core.metrics.metrics_controller import router as metrics_router


v1_router = APIRouter(prefix="/v1", tags=[])
v1_router.include_router(my_entity_router)
v1_router.include_router(metrics_router)
v1_router.include_router(cache_my_entity_router)
