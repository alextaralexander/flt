"""Базовый репозиторий."""

from typing import Any, Generic, List, Set, TypeVar, Union
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta, selectinload

from py_main_lib.entities.alchemy import BaseEntityModel


M = TypeVar("M", bound=BaseEntityModel)  # Модель
CD = TypeVar("CD", bound=BaseModel)  # CREATE Схема данных
UD = TypeVar("UD", bound=BaseModel)  # UPDATE Схема данных


class BaseDAO(Generic[M, CD, UD]):
    """Базовый репозиторий для работы с моделями."""

    model: DeclarativeMeta
    awaitable_attrs_: Set["str"] | None = None

    @classmethod
    def get_select_query(cls) -> Select:
        """Возвращает базовый запрос для моделей."""
        if not cls.awaitable_attrs_:
            return select(cls.model)
        else:
            sel = select(cls.model)
            for awaitable_attr_ in cls.awaitable_attrs_:
                sel = sel.options(selectinload(getattr(cls.model, awaitable_attr_)))
            return sel

    @classmethod
    async def get_all(cls, session: AsyncSession) -> List[M]:
        """Возвращает весь список объектов модели"""
        query = cls.get_select_query()
        result = await session.execute(query)
        result_typed: List[M] = result.scalars().unique().all()
        return result_typed

    @classmethod
    async def get_list_by_owner(cls, user_id: str, session: AsyncSession) -> Union[List[M], Any]:
        """Возвращает список моделей, что были созданы пользователем."""
        query = cls.get_select_query().filter_by(created_by=user_id)
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def get_by_id(cls, obj_id: UUID, session: AsyncSession) -> M | None:
        """Получить запись по ID."""
        result = await session.execute(cls.get_select_query().filter_by(id=str(obj_id)))
        result_typed: M | None = result.scalar_one_or_none()
        return result_typed

    @classmethod
    async def create(cls, data: CD, user_id: str, session: AsyncSession) -> M:
        """Создание новой записи и возврат объекта модели."""
        instance: M = cls.model(**data.model_dump())
        instance.created_by = user_id
        session.add(instance)
        await session.flush()
        await cls.load_awaitable_attrs(instance)
        return instance

    @classmethod
    async def update(cls, model: M, data: UD, user_id: str, session: AsyncSession) -> M:
        """Обновление существующей записи."""
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(model, key, value)
        model.last_modified_by = user_id
        await session.flush()
        await cls.load_awaitable_attrs(model)
        return model

    @staticmethod
    async def hard_delete(model: M, session: AsyncSession) -> bool:
        """Удаление существующей записи."""
        await session.delete(model)
        return True

    @staticmethod
    async def bool_delete(model: M, user_id: str) -> M:
        """Маркировка записи как is_deleted."""
        model.is_deleted = True
        model.last_modified_by = user_id
        return model

    @classmethod
    async def load_awaitable_attrs(cls, instance):
        if cls.awaitable_attrs_:
            for awaitable_attr_ in cls.awaitable_attrs_:
                await getattr(instance.awaitable_attrs, awaitable_attr_)
