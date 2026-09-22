"""Модели базы данных (типизированный стиль SQLAlchemy 2.0: Mapped + mapped_column)."""

from py_main_lib.entities.alchemy import BaseEntityModel
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.dao.db_helpers.base import Base


class SchemaBase(Base):
    """Общий абстрактный предок моделей сервиса (место для table_args/схемы)."""

    __abstract__ = True


class MyEntity(BaseEntityModel, SchemaBase):
    """Пример сущности; служебные колонки (id, created_by, ...) даёт BaseEntityModel."""

    __tablename__ = "my_entity"

    name: Mapped[str] = mapped_column(String, comment="Название")
