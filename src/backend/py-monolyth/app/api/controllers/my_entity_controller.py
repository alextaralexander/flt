"""Пример реализации контроллера.

Контроллер — модульный `APIRouter` с декораторами: тонкий HTTP-слой,
который связывает маршруты с методами сервиса. Сервис приходит через
`Depends()` — в тестах его можно подменить `dependency_overrides`.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, Security, status
from py_main_lib.filter_utils.schemas.filter_schema import FilterSchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.my_entity_schema import (
    CreateMyEntitySchema,
    FilteredMyEntityResponse,
    MyEntityResponse,
    UpdateMyEntitySchema,
)
from app.api.services.my_entity_service import MyEntityService
from app.core.dao.db_helpers.db_connection import get_session
from app.core.security.permissions import MyEntityPermissions
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user


router = APIRouter(prefix="/my_entity", tags=["my_entity_api"])

ServiceDep = Annotated[MyEntityService, Depends()]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Создание нового объекта",
    description="Создание нового объекта",
    operation_id="create_my_entity",
)
async def create_object(
    create_dto: CreateMyEntitySchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.CREATE_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> MyEntityResponse:
    """Создание нового объекта.

    Args:
        create_dto: Данные для создания объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `MyEntity`.
        session: Асинхронная сессия базы данных.

    Returns:
        Созданный объект.
    """
    result = await service.create_object(create_dto, user, session)
    return MyEntityResponse(payload=result)


@router.post(
    "/filter",
    status_code=status.HTTP_200_OK,
    summary="Фильтрация объектов по заданным критериям",
    description="Фильтрация объектов по заданным критериям",
    operation_id="filter_my_entities",
)
async def get_filtered_list(
    filter_dto: FilterSchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.GET_LIST])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> FilteredMyEntityResponse:
    """Получение списка объектов с фильтрацией.

    Args:
        filter_dto: Параметры фильтрации.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `MyEntity`.
        session: Асинхронная сессия базы данных.

    Returns:
        Отфильтрованный список объектов.
    """
    payload = await service.get_objects_filtered(filter_dto, user, session)
    return FilteredMyEntityResponse(payload=payload.model_dump())


@router.get(
    "/{obj_id}",
    status_code=status.HTTP_200_OK,
    summary="Получение объекта по ID",
    description="Получение объекта по ID",
    operation_id="get_my_entity",
)
async def get_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.GET_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> MyEntityResponse:
    """Получение объекта по ID.

    Args:
        obj_id: ID объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `MyEntity`.
        session: Асинхронная сессия базы данных.

    Returns:
        Найденный объект.
    """
    result = await service.get_object_by_id(obj_id, user, session)
    return MyEntityResponse(payload=result)


@router.put(
    "/{obj_id}",
    status_code=status.HTTP_200_OK,
    summary="Обновление объекта по ID",
    description="Обновление объекта по ID",
    operation_id="update_my_entity",
)
async def update_object(
    obj_id: UUID,
    update_dto: UpdateMyEntitySchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.UPDATE_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> MyEntityResponse:
    """Обновление объекта по ID.

    Args:
        obj_id: ID объекта.
        update_dto: Данные для обновления объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `MyEntity`.
        session: Асинхронная сессия базы данных.

    Returns:
        Обновлённый объект.
    """
    result = await service.update_object(obj_id, update_dto, user, session)
    return MyEntityResponse(payload=result)


@router.delete(
    "/{obj_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление объекта по ID",
    description="Удаление объекта по ID",
    operation_id="delete_my_entity",
)
async def delete_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[MyEntityPermissions.DELETE_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> Response:
    """Удаление объекта по ID (логическое, через `is_deleted`).

    Args:
        obj_id: ID объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `MyEntity`.
        session: Асинхронная сессия базы данных.
    """
    await service.delete_object(obj_id, user, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
