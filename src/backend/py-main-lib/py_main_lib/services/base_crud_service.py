"""Сервис для работы с моделью."""

from typing import Any, Dict, Generic, Tuple, TypeVar, Union
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from py_main_lib.dao.base_dao import CD, UD, BaseDAO, M
from py_main_lib.db_utils import transaction_context
from py_main_lib.filter_utils.entity_filters import (
    BASE_FILTER_CONDITIONS,
    EntityFilter,
)
from py_main_lib.filter_utils.schemas.filter_schema import (
    PM,
    FilterFuncType,
    FilterResult,
    FilterSchema,
)
from py_main_lib.security.schemas import UserSecuritySchema


DAO = TypeVar("DAO", bound=BaseDAO)


class BaseService(Generic[PM, CD, UD]):
    """Сервис для работы с типизированным репозиторием."""

    dao: BaseDAO
    schema: PM
    filter_conditions: Dict[str, FilterFuncType]
    sort_conditions: Union[Tuple[str, ...], Tuple[()]]

    async def get_objects_filtered(
        self,
        filter_dto: FilterSchema,
        user: UserSecuritySchema,
        session: AsyncSession,
        begin_query=None,
        logger: Any = None,
    ) -> FilterResult:
        """Получение FilterResult со списком моделей."""
        ef = EntityFilter(
            repo=self.dao,
            filter_fields_conditions=self.filter_conditions,
            sort_fields=self.sort_conditions,
            base_filter_conditions=BASE_FILTER_CONDITIONS,
            begin_query=begin_query,
            logger=logger,
        )
        async with transaction_context(session):
            pagination = await ef.filter(filter_dto, session)
        fr = FilterResult[PM](
            page_size=len(pagination.objects),
            current_page=pagination.page,
            elements_count=pagination.total,
            page_count=pagination.total_pages,
            result=[self.schema.model_validate(obj) for obj in pagination.objects],
        )
        return fr

    async def get_object_by_id(self, obj_id: UUID, user: UserSecuritySchema | None, session: AsyncSession):
        """Получение модели по ID."""
        async with transaction_context(session):
            obj = await self.dao.get_by_id(obj_id, session)
            if not obj:
                raise HTTPException(status_code=404, detail="Object with such id not found")
        return obj

    async def create_object(self, data: CD, user: UserSecuritySchema, session: AsyncSession) -> M:
        """Создание новой модели через репозиторий."""
        async with transaction_context(session):
            obj: M = await self.dao.create(data, user.user_id, session)
        return obj

    async def update_object(
        self, obj_id: UUID, data: UD, user: UserSecuritySchema, session: AsyncSession
    ) -> Union[M, None]:
        """Обновление модели через репозиторий."""
        async with transaction_context(session):
            obj = await self.dao.get_by_id(obj_id, session)
            # check_access_to_model(obj, user.user_id)
            updated_obj: M = await self.dao.update(obj, data, user.user_id, session)
        return updated_obj

    async def delete_object(self, obj_id: UUID, user: UserSecuritySchema, session: AsyncSession) -> Union[bool, None]:
        """Удаление модели через репозиторий."""
        async with transaction_context(session):
            obj = await self.dao.get_by_id(obj_id, session)
            # check_access_to_model(obj, user.user_id)
            await self.dao.bool_delete(obj, user.user_id)
        return True
