"""Общий env Alembic для всех модулей (ADR-002, раздел 3.4; ADR-003, раздел 2.5).

Модуль задаёт секция `alembic.ini`, выбранная ключом `-n <module>`
(`alembic -n identity upgrade head`): параметр `flt_module` указывает пакет
`app/modules/<module>`, из `module.py` которого берутся метаданные моделей.
Каждый модуль мигрирует только свою схему PostgreSQL `<module>` и хранит свою
таблицу `alembic_version` в ней же. Запуск без `-n` (секция `[alembic]`) запрещён.
"""

import asyncio

from alembic import context
from sqlalchemy import Connection, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.logging import logger_settings
from app.core.modules import load_module
from configs.settings import settings


# Таймауты DDL (ADR-003, раздел 2.5, п. 6; SYS-05): миграция не ждёт блокировку бесконечно.
MIGRATION_LOCK_TIMEOUT = "5s"
MIGRATION_STATEMENT_TIMEOUT = "60s"

config = context.config
logger_settings.setup_logging()

module_name = config.get_section_option(config.config_ini_section, "flt_module")
if not module_name or not module_name.isidentifier():
    raise RuntimeError(
        "Укажите модуль: `alembic -n <module> ...` (секция модуля в alembic.ini с параметром flt_module); "
        "миграции всех модулей — `make migrate`."
    )

target_metadata = load_module(module_name).metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Autogenerate видит только схему своего модуля: чужие схемы и `public` игнорируются."""
    if type_ == "schema":
        return name == module_name
    return True


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    """Общая конфигурация контекста миграций модуля (online и offline)."""
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        version_table_schema=module_name,
        include_schemas=True,
        include_name=include_name,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"} if connection is None else None,
    )


def run_migrations_offline() -> None:
    """Генерирует SQL миграций модуля без подключения к БД (`alembic -n <module> upgrade head --sql`)."""
    _configure(url=settings.sqlalchemy_database_uri)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Создаёт схему модуля, выставляет таймауты DDL и прогоняет миграции в одной транзакции."""
    connection.execute(text(f"SET lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'"))
    connection.execute(text(f"SET statement_timeout = '{MIGRATION_STATEMENT_TIMEOUT}'"))
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{module_name}"'))
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Подключается к PostgreSQL (без пула) и выполняет миграции модуля."""
    connectable = create_async_engine(settings.sqlalchemy_database_uri, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await connectable.dispose()


def run_migrations_online() -> None:
    """Online-режим: миграции модуля на реальной БД."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
