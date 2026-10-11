"""Фикстуры архитектурных тестов (ADR-002, раздел 3.6; SYS-05; SYS-10-R8).

Проверки выполняются над двумя деревьями:

- текущее дерево сервиса — модули реестра `app/modules/registry.py` (на этапе 1 до Г.5 реестр пуст);
- копия дерева во временном каталоге с модулями-образцами `identity` и `llm_gateway`,
  созданными скаффолдером (`python -m cli add-module`, `add-entity`, `add-subscriber`), —
  чтобы тесты были содержательными и на пустом реестре и доказывали, что сгенерированный
  код соблюдает границы. Описания модулей копии проверяются в отдельном процессе
  (`python -m tests.architecture.checks`), потому что пакет `app` копии нельзя импортировать
  рядом с пакетом `app` текущего процесса.
"""

import json
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

from app.core.modules import ModuleDefinition, load_modules
from app.modules.registry import MODULES
from tests.architecture.checks import REPORT_MARKER, SERVICE_ROOT


# SYS-03-R2: дополнительные префиксы REST допускаются только по таблице раздела 6 SYS-03
# (Analytics/Specs/_system/SYS-03-rest-api-conventions.md); единственное исключение — `/api/v1/auth`
# модуля `identity` (OQ-12). Новый префикс — сначала правка SYS-03, затем этой константы.
ALLOWED_EXTRA_PREFIXES: dict[str, tuple[str, ...]] = {"identity": ("/api/v1/auth",)}

# Модули-образцы в порядке реестра (нижние уровни SYS-01 раньше) и их REST-сущности.
SAMPLE_MODULES: dict[str, str] = {"identity": "User", "llm_gateway": "ProviderKey"}
# Консьюмер события располагается выше издателя (SYS-01-R7): llm_gateway слушает identity.
SAMPLE_SUBSCRIBER = ("llm_gateway", "USER_DELETED", "flt.identity.user_deleted.v1")

COPIED = ("app", "cli", "configs", "envs", "pyproject.toml", "alembic.ini", ".importlinter")
IGNORED = shutil.ignore_patterns("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".import_linter_cache")


def run_in_tree(
    tree: Path, *args: str, tool: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Запускает интерпретатор или консольный скрипт venv в дереве `tree` (аргументы задаёт тест).

    Args:
        tree: Корень дерева сервиса (cwd и PYTHONPATH процесса).
        *args: Аргументы команды.
        tool: Имя консольного скрипта venv (`lint-imports`); None — текущий интерпретатор.
        check: Требовать код возврата 0.

    Returns:
        Результат процесса с stdout и stderr.
    """
    command = [str(Path(sys.executable).parent / tool), *args] if tool else [sys.executable, *args]
    result = subprocess.run(  # nosec B603
        command,
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(tree)},
    )
    if check:
        assert result.returncode == 0, f"{command}:\n{result.stdout}\n{result.stderr}"
    return result


def copy_service_tree(destination: Path, source: Path = SERVICE_ROOT) -> Path:
    """Копирует дерево сервиса, нужное скаффолдеру, import-linter и проверкам, в `destination`.

    Returns:
        Корень копии.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for name in COPIED:
        path = source / name
        if path.is_dir():
            shutil.copytree(path, destination / name, ignore=IGNORED)
        elif path.exists():
            shutil.copy2(path, destination / name)
    (destination / "tests").mkdir(exist_ok=True)
    shutil.copy2(source / "tests" / "__init__.py", destination / "tests" / "__init__.py")
    shutil.copytree(source / "tests" / "architecture", destination / "tests" / "architecture", ignore=IGNORED)
    return destination


@pytest.fixture(scope="session")
def registry_modules() -> list[ModuleDefinition]:
    """Описания модулей реестра текущего дерева."""
    return load_modules(MODULES)


@pytest.fixture(scope="session")
def sample_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Копия дерева сервиса с модулями-образцами, сгенерированными скаффолдером."""
    tree = copy_service_tree(tmp_path_factory.mktemp("arch") / "service")
    for module, entity in SAMPLE_MODULES.items():
        run_in_tree(tree, "-m", "cli", "add-module", module)
        run_in_tree(tree, "-m", "cli", "add-entity", entity, "--module", module)
    module, topic, value = SAMPLE_SUBSCRIBER
    run_in_tree(tree, "-m", "cli", "add-subscriber", topic, value, "--module", module)
    return tree


@pytest.fixture(scope="session")
def sample_report(sample_tree: Path) -> dict[str, list[str]]:
    """JSON-отчёт проверок описаний модулей копии дерева (`python -m tests.architecture.checks`)."""
    stdout = run_in_tree(sample_tree, "-m", "tests.architecture.checks").stdout
    [line] = [line for line in stdout.splitlines() if line.startswith(REPORT_MARKER)]
    report: dict[str, list[str]] = json.loads(line.removeprefix(REPORT_MARKER))
    return report
