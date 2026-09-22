"""Репозиторий для работы с MyEntityModel."""

from py_main_lib.dao.base_dao import BaseDAO

from app.api.schemas.my_entity_schema import CreateMyEntitySchema, UpdateMyEntitySchema
from app.core.dao.models import MyEntity


class MyEntityDAO(BaseDAO[MyEntity, CreateMyEntitySchema, UpdateMyEntitySchema]):
    """Репозиторий для работы с MyEntity моделью."""

    model = MyEntity
