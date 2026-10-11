"""Тесты скаффолдера модулей (ADR-002, раздел 3.7).

Модуль, сущность и Kafka-консьюмер генерируются во временной копии дерева сервиса,
затем результат проверяется теми же инструментами, что и `make check`:
сгенерированный код обязан проходить их без правок. Миграция модуля создаётся
autogenerate-ом, накатывается на тестовую БД и откатывается.
"""

import os
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[2]
COPIED = ("app", "cli", "configs", "envs", "tests", "pyproject.toml", "alembic.ini", ".importlinter")
IGNORED = shutil.ignore_patterns("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache")
MODULE = "sample_mod"
TOPIC = "flt.sample_mod.order_placed.v1"
STANDS = ("local", "dev", "test", "prod")

pytestmark = pytest.mark.no_db


def _run(tree: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Запустить команду в копии дерева тем же интерпретатором (аргументы фиксированы тестом)."""
    result = subprocess.run(  # nosec B603
        [sys.executable, *args],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(tree)},
    )
    if check:
        assert result.returncode == 0, f"{args}:\n{result.stdout}\n{result.stderr}"
    return result


@pytest.fixture(scope="module")
def scaffolded_tree(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Копия дерева сервиса с модулем, REST-сущностью и Kafka-консьюмером, созданными скаффолдером."""
    tree = tmp_path_factory.mktemp("scaffold")
    for name in COPIED:
        source = SERVICE_ROOT / name
        if source.is_dir():
            shutil.copytree(source, tree / name, ignore=IGNORED)
        elif source.exists():
            shutil.copy2(source, tree / name)

    _run(tree, "-m", "cli", "add-module", MODULE)
    _run(tree, "-m", "cli", "add-entity", "OrderItem", "--module", MODULE)
    _run(tree, "-m", "cli", "add-subscriber", "ORDER_PLACED", TOPIC, "--module", MODULE)
    yield tree


class TestScaffoldedModule:
    """Структура и регистрация модуля."""

    def test_layout_and_registration(self, scaffolded_tree: Path) -> None:
        """Пакет модуля, реестр, секция alembic.ini, env-файлы стендов и тесты созданы."""
        # - Arrange -
        base = scaffolded_tree / "app" / "modules" / MODULE

        # - Assert -
        for rel_path in (
            "module.py",
            "public/__init__.py",
            "models/__init__.py",
            "models/order_item.py",
            "settings.py",
            "permissions.py",
            "api/router.py",
            "api/order_item_controller.py",
            "brokers/router.py",
            "brokers/subscribers.py",
            "migrations/versions/.gitkeep",
        ):
            assert (base / rel_path).exists(), rel_path
        assert _run(scaffolded_tree, "-m", "cli", "list-modules").stdout.split() == [MODULE]
        alembic_ini = (scaffolded_tree / "alembic.ini").read_text(encoding="utf-8")
        assert f"[{MODULE}]" in alembic_ini
        assert f"flt_module = {MODULE}" in alembic_ini
        for stand in STANDS:
            assert (scaffolded_tree / "envs" / stand / f"{MODULE}_{stand}.env").exists()
        assert (scaffolded_tree / "tests" / "modules" / MODULE / "conftest.py").exists()

    def test_generation_is_idempotent(self, scaffolded_tree: Path) -> None:
        """Повторный запуск не меняет файлы и не дублирует регистрацию."""
        # - Arrange -
        watched = [
            scaffolded_tree / "app" / "modules" / "registry.py",
            scaffolded_tree / "alembic.ini",
            scaffolded_tree / "app" / "modules" / MODULE / "module.py",
            scaffolded_tree / "app" / "modules" / MODULE / "api" / "router.py",
            scaffolded_tree / "app" / "modules" / MODULE / "brokers" / "subscribers.py",
        ]
        before = [path.read_text(encoding="utf-8") for path in watched]

        # - Act -
        _run(scaffolded_tree, "-m", "cli", "add-module", MODULE)
        _run(scaffolded_tree, "-m", "cli", "add-entity", "OrderItem", "--module", MODULE)
        _run(scaffolded_tree, "-m", "cli", "add-subscriber", "ORDER_PLACED", TOPIC, "--module", MODULE)

        # - Assert -
        assert [path.read_text(encoding="utf-8") for path in watched] == before

    def test_module_definition_is_wired(self, scaffolded_tree: Path) -> None:
        """`ModuleDefinition` загружается: префикс REST, Kafka-роутер, схема и права модуля."""
        # - Act -
        script = (
            "from app.core.modules import load_modules\n"
            "from app.modules.registry import MODULES\n"
            "[m] = load_modules(MODULES)\n"
            "from app.main import create_app\n"
            "print('@@', m.router.prefix)\n"
            "print('@@', sorted(create_app([m]).openapi()['paths'])[0])\n"
            "print('@@', m.kafka_router is not None)\n"
            "print('@@', sorted({t.schema for t in m.metadata.tables.values()}))\n"
            "print('@@', ','.join(m.permissions))\n"
            "print('@@', m.settings.model_config['env_prefix'])\n"
        )
        stdout = _run(scaffolded_tree, "-c", script).stdout
        output = [line.removeprefix("@@ ") for line in stdout.splitlines() if line.startswith("@@ ")]

        # - Assert -
        assert output == [
            "/api/v1/sample-mod",
            "/api/v1/sample-mod/order-items/",
            "True",
            "['sample_mod']",
            "sample_mod:order_items:create,sample_mod:order_items:delete,"
            "sample_mod:order_items:read,sample_mod:order_items:update",
            "SAMPLE_MOD_",
        ]


class TestScaffoldedCodeQuality:
    """Сгенерированный код проходит проверки `make check` без правок."""

    def test_ruff_lint_and_format(self, scaffolded_tree: Path) -> None:
        """Проверки ruff (check и format --check) проходят без замечаний."""
        # - Act / Assert -
        _run(scaffolded_tree, "-m", "ruff", "check", ".")
        _run(scaffolded_tree, "-m", "ruff", "format", "--check", ".")

    def test_mypy_strict(self, scaffolded_tree: Path) -> None:
        """Проверка mypy strict проходит на app, cli, configs с новым модулем."""
        # - Act / Assert -
        _run(scaffolded_tree, "-m", "mypy", "app", "cli", "configs")


class TestScaffoldedMigrations:
    """`make makemigration module=…` и `make migrate` работают для нового модуля."""

    def test_autogenerate_upgrade_and_downgrade(self, scaffolded_tree: Path) -> None:
        """Autogenerate создаёт таблицу в схеме модуля; upgrade и downgrade проходят."""
        # - Act -
        _run(scaffolded_tree, "-m", "alembic", "-n", MODULE, "revision", "--autogenerate", "-m", "init")
        revisions = list((scaffolded_tree / "app" / "modules" / MODULE / "migrations" / "versions").glob("*.py"))
        upgrade = _run(scaffolded_tree, "-m", "alembic", "-n", MODULE, "upgrade", "head")
        downgrade = _run(scaffolded_tree, "-m", "alembic", "-n", MODULE, "downgrade", "base")
        _run(scaffolded_tree, "-c", _DROP_SCHEMA_SCRIPT)

        # - Assert -
        assert len(revisions) == 1
        revision = revisions[0].read_text(encoding="utf-8")
        assert "op.create_table(" in revision
        assert "schema='sample_mod'" in revision or 'schema="sample_mod"' in revision
        assert upgrade.returncode == 0
        assert downgrade.returncode == 0


_DROP_SCHEMA_SCRIPT = """
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from configs.settings import settings

async def main() -> None:
    engine = create_async_engine(settings.sqlalchemy_database_uri)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS sample_mod CASCADE"))
    await engine.dispose()

asyncio.run(main())
"""
