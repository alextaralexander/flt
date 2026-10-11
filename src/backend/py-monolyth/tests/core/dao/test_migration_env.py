"""Тесты общего `env.py` Alembic: секция и схема на модуль, таймауты DDL (ADR-002 3.4, ADR-003 2.5).

Модуль-образец регистрируется в `sys.modules` (на диске его нет), ревизия лежит во
временном каталоге; миграции идут на тестовую БД и откатываются в конце теста.
"""

import asyncio
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.modules import ModuleDefinition
from configs.settings import settings


pytestmark = [pytest.mark.req("SYS-05-R36"), pytest.mark.req("SYS-05-R38")]

PROBE_MODULE = "probe_migrations"

REVISION = '''"""probe revision."""

from alembic import op


revision = "probe0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Таблица в схеме модуля фиксирует таймауты соединения миграции."""
    op.execute(
        "CREATE TABLE probe_migrations.ddl_settings AS "
        "SELECT current_setting('lock_timeout') AS lock_timeout, "
        "current_setting('statement_timeout') AS statement_timeout"
    )


def downgrade() -> None:
    """Удаление таблицы-пробы."""
    op.execute("DROP TABLE probe_migrations.ddl_settings")
'''


def _fetch(sql: str) -> list[tuple[object, ...]]:
    """Выполнить запрос к тестовой БД отдельным коротким соединением."""

    async def run() -> list[tuple[object, ...]]:
        engine = create_async_engine(settings.sqlalchemy_database_uri)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(sql))
                return [tuple(row) for row in result.fetchall()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def probe_module(tmp_path: Path) -> Iterator[Config]:
    """Модуль-проба с одной ревизией и конфигурация Alembic его секции."""
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "probe0001_init.py").write_text(REVISION, encoding="utf-8")

    module_py = types.ModuleType(f"app.modules.{PROBE_MODULE}.module")
    module_py.module = ModuleDefinition(  # type: ignore[attr-defined]
        name=PROBE_MODULE, metadata=MetaData(schema=PROBE_MODULE)
    )
    sys.modules[f"app.modules.{PROBE_MODULE}"] = types.ModuleType(f"app.modules.{PROBE_MODULE}")
    sys.modules[f"app.modules.{PROBE_MODULE}.module"] = module_py

    config = Config(ini_section=PROBE_MODULE)
    config.set_section_option(PROBE_MODULE, "script_location", "app/core/dao/db_helpers/migrations")
    config.set_section_option(PROBE_MODULE, "version_locations", str(versions))
    config.set_section_option(PROBE_MODULE, "path_separator", "os")
    config.set_section_option(PROBE_MODULE, "flt_module", PROBE_MODULE)
    yield config

    sys.modules.pop(f"app.modules.{PROBE_MODULE}.module", None)
    sys.modules.pop(f"app.modules.{PROBE_MODULE}", None)
    _fetch(f"DROP SCHEMA IF EXISTS {PROBE_MODULE} CASCADE")


class TestModuleMigrations:
    """Миграции модуля изолированы в его схеме (Arrange / Act / Assert / Clean)."""

    def test_upgrade_creates_schema_version_table_and_sets_timeouts(self, probe_module: Config) -> None:
        """`upgrade head` создаёт схему модуля, его `alembic_version` и выполняет DDL с таймаутами."""
        # - Act -
        command.upgrade(probe_module, "head")

        # - Assert -
        tables = _fetch(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{PROBE_MODULE}' ORDER BY table_name"
        )
        assert tables == [("alembic_version",), ("ddl_settings",)]
        assert _fetch(f"SELECT version_num FROM {PROBE_MODULE}.alembic_version") == [("probe0001",)]
        assert _fetch(f"SELECT lock_timeout, statement_timeout FROM {PROBE_MODULE}.ddl_settings") == [("5s", "1min")]

        # - Clean -
        command.downgrade(probe_module, "base")
        assert _fetch(f"SELECT count(*) FROM {PROBE_MODULE}.alembic_version") == [(0,)]

    def test_offline_mode_renders_sql(self, probe_module: Config, capsys: pytest.CaptureFixture[str]) -> None:
        """`--sql` генерирует DDL модуля без подключения к БД."""
        # - Act -
        command.upgrade(probe_module, "head", sql=True)

        # - Assert -
        output = capsys.readouterr().out
        assert "CREATE TABLE probe_migrations.ddl_settings" in output
        assert "probe_migrations.alembic_version" in output


def test_running_without_module_section_fails() -> None:
    """Секция `[alembic]` без `flt_module` запрещена: env.py просит указать модуль."""
    # - Arrange -
    config = Config("alembic.ini")

    # - Act / Assert -
    with pytest.raises(RuntimeError, match="Укажите модуль"):
        command.upgrade(config, "head")


def test_alembic_ini_has_no_credentials() -> None:
    """В `alembic.ini` нет адреса БД с учётными данными (ADR-003, ADR-013)."""
    # - Act -
    content = Path("alembic.ini").read_text(encoding="utf-8")

    # - Assert -
    assert "sqlalchemy.url" not in content
