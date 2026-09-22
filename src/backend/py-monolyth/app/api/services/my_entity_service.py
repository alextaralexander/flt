"""Пример реализации сервиса."""

from typing import Any, ClassVar
from uuid import UUID

from py_main_lib.db_utils import transaction_context
from py_main_lib.filter_utils.base_compare_methods import equals, like_
from py_main_lib.security.schemas import UserSecuritySchema
from py_main_lib.services.base_crud_service import BaseService
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dao.my_entity_dao import MyEntityDAO
from app.api.schemas.my_entity_schema import (
    CreateMyEntitySchema,
    MyEntitySchema,
    UpdateMyEntitySchema,
)
from app.core.dao.models import MyEntity
from app.core.exceptions import ModelNotFoundInDatabaseError


class MyEntityService(BaseService[MyEntitySchema, CreateMyEntitySchema, UpdateMyEntitySchema]):
    """Сервис, содержащий выполнение бизнес-логики для сущности `MyEntity`.

    Если мы хотим иметь базовые операции для выполнения бизнес-логики, то следует наследоваться от `BaseService`.
    - `dao` - объект класса для доступа к Persistence Layer.
    - `schema` - при наследовании от BaseService следует указать. Схема для вывода результата фильтрации.
    - `filter_conditions` - при наследовании от BaseService следует указать. Логика выполнения фильтрации.
    - `sort_conditions` - при наследовании от BaseService следует указать. Доступные сортировки.
    """

    dao = MyEntityDAO
    schema = MyEntitySchema
    filter_conditions: ClassVar[dict[str, Any]] = {"name": like_, "created_by": equals}
    sort_conditions = ("name",)

    async def get_object_by_id(self, obj_id: UUID, user: UserSecuritySchema, session: AsyncSession) -> MyEntity:
        """Пример сервисного метода: перезаписывает метод из BaseService.

        Метод выполняется в одной транзакции (`transaction_context`).

        Args:
            obj_id: ID объекта.
            user: Пользователь, выполняющий запрос.
            session: Асинхронная сессия базы данных.

        Returns:
            Найденный объект.

        Raises:
            ModelNotFoundInDatabaseError: объект не найден или помечен удалённым.
        """
        async with transaction_context(session):
            obj: MyEntity | None = await self.dao.get_by_id(obj_id, session)
            if not obj:
                raise ModelNotFoundInDatabaseError(model_id=str(obj_id), model=MyEntity)
            if obj.is_deleted:
                raise ModelNotFoundInDatabaseError(model_id=str(obj_id), model=MyEntity, is_deleted=obj.is_deleted)
        return obj
