"""Декларативная база моделей SQLAlchemy 2.0.

Вынесена отдельно от подключения к БД: импорт моделей (например, в Alembic
autogenerate или скриптах) не должен тянуть за собой создание engine.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


# Стабильные имена constraint-ов/индексов: autogenerate-миграции получаются
# детерминированными, а downgrade не зависит от имён, придуманных СУБД.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс всех моделей проекта."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
