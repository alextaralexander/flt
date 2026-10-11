"""Декларативные базы моделей SQLAlchemy 2.0: своя схема PostgreSQL на модуль (ADR-002, ADR-003).

Вынесено отдельно от подключения к БД: импорт моделей (Alembic autogenerate, скрипты,
тесты) не тянет за собой создание engine.
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


def module_metadata(schema: str) -> MetaData:
    """Метаданные моделей модуля: схема PostgreSQL `schema` и общая конвенция имён.

    Args:
        schema: Имя модуля — оно же имя схемы PostgreSQL.

    Returns:
        Новый объект `MetaData(schema=schema, naming_convention=NAMING_CONVENTION)`.

    Raises:
        ValueError: имя схемы пустое, не идентификатор или `public` (схема `public` таблиц не содержит, ADR-003).
    """
    if not schema.isidentifier() or schema == "public":
        raise ValueError(f"Недопустимая схема модуля: {schema!r}.")
    return MetaData(schema=schema, naming_convention=NAMING_CONVENTION)


def make_module_base(schema: str) -> type[DeclarativeBase]:
    """Создаёт декларативную базу моделей модуля: все её таблицы живут в схеме `schema`.

    Для динамического создания базы (тесты, инструменты). В коде модуля база объявляется
    классом, чтобы mypy видел её как тип (так генерирует скаффолдер):

        class Base(DeclarativeBase):
            metadata = module_metadata("<module>")

    Args:
        schema: Имя модуля — оно же имя схемы PostgreSQL.

    Returns:
        Новый класс `DeclarativeBase` с метаданными `module_metadata(schema)`.

    Raises:
        ValueError: недопустимое имя схемы (см. `module_metadata`).
    """
    metadata_of_module = module_metadata(schema)

    class Base(DeclarativeBase):
        """Базовый класс моделей одного модуля (схема задаётся `metadata`)."""

        metadata = metadata_of_module

    Base.__doc__ = f"Базовый класс моделей модуля `{schema}` (схема PostgreSQL `{schema}`)."
    return Base
