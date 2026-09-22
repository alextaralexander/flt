"""Пример реализации контроллера с кэшированием (Redis вместо БД)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, Security, status

from app.api.schemas.caching_schemas.cache_entity_schema import (
    CacheMyEntityResponse,
    CreateCacheMyEntitySchema,
    UpdateCacheMyEntitySchema,
)
from app.api.services.caching_services.cache_my_entity_service import (
    CacheMyEntityService,
)
from app.core.security.permissions import MyEntityPermissions
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user


router = APIRouter(prefix="/cache/my_entity", tags=["caching_my_entity_api"])

CacheServiceDep = Annotated[CacheMyEntityService, Depends()]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Создание нового объекта",
    description="Создание нового объекта",
    operation_id="create_cached_my_entity",
)
async def create_object(
    create_dto: CreateCacheMyEntitySchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.CREATE_MODEL])),
    ],
    cache_service: CacheServiceDep,
) -> CacheMyEntityResponse:
    """Создание нового объекта в кэше.

    Args:
        create_dto: Данные для создания объекта.
        user: Пользователь, выполняющий запрос.
        cache_service: Сервис для кэширования.

    Returns:
        Созданный объект.
    """
    result = await cache_service.save_data(create_dto)
    return CacheMyEntityResponse(payload=result)


@router.get(
    "/{obj_id}",
    status_code=status.HTTP_200_OK,
    summary="Получение объекта по ID",
    description="Получение объекта по ID",
    operation_id="get_cached_my_entity",
)
async def get_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.GET_MODEL])),
    ],
    cache_service: CacheServiceDep,
) -> CacheMyEntityResponse:
    """Получение объекта по ID.

    Args:
        obj_id: ID объекта.
        user: Пользователь, выполняющий запрос.
        cache_service: Сервис для кэширования.

    Returns:
        Найденный объект.
    """
    result = await cache_service.get_cached_data(obj_id)
    return CacheMyEntityResponse(payload=result)


@router.put(
    "/{obj_id}",
    status_code=status.HTTP_200_OK,
    summary="Обновление объекта по ID",
    description="Обновление объекта по ID",
    operation_id="update_cached_my_entity",
)
async def update_object(
    obj_id: UUID,
    update_dto: UpdateCacheMyEntitySchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.UPDATE_MODEL])),
    ],
    cache_service: CacheServiceDep,
) -> CacheMyEntityResponse:
    """Обновление объекта по ID.

    Args:
        obj_id: ID объекта.
        update_dto: Данные для обновления объекта.
        user: Пользователь, выполняющий запрос.
        cache_service: Сервис для кэширования.

    Returns:
        Обновлённый объект.
    """
    result = await cache_service.update_data(update_dto)
    return CacheMyEntityResponse(payload=result)


@router.delete(
    "/{obj_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление объекта по ID",
    description="Удаление объекта по ID",
    operation_id="delete_cached_my_entity",
)
async def delete_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.DELETE_MODEL])),
    ],
    cache_service: CacheServiceDep,
) -> Response:
    """Удаление объекта по ID.

    Args:
        obj_id: ID объекта.
        user: Пользователь, выполняющий запрос.
        cache_service: Сервис для кэширования.
    """
    await cache_service.delete_data(obj_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
