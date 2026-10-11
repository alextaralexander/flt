"""Реестр модулей, контракты `.importlinter`, секции `alembic.ini` и карта модулей SYS-01 согласованы.

ADR-002 §3.6 (`test_registry_and_contracts_are_complete`), SYS-01-R1, SYS-01-R4, SYS-01-R10.
"""

import shutil
from pathlib import Path

import pytest

from tests.architecture import checks
from tests.architecture.conftest import IGNORED, SAMPLE_MODULES, run_in_tree


pytestmark = pytest.mark.no_db


@pytest.fixture(scope="module")
def sys01_layers() -> list[list[str]]:
    """Строки таблицы 3.3 SYS-01 (порядок слоёв контракта `modules-dependency-order`)."""
    return checks.parse_sys01_layers()


@pytest.mark.req("SYS-01-R4")
class TestRegistryAndContractsAreComplete:
    """Каждый модуль есть в каталогах, `MODULES`, контрактах 1–3 и `alembic.ini`, и наоборот."""

    def test_current_tree(self) -> None:
        """Текущее дерево согласовано."""
        # - Act / Assert -
        assert checks.registry_completeness_violations(checks.SERVICE_ROOT) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Скаффолдер регистрирует модули-образцы во всех источниках."""
        # - Act -
        violations = checks.registry_completeness_violations(sample_tree)

        # - Assert -
        assert checks.read_registry(sample_tree) == tuple(SAMPLE_MODULES)
        assert violations == []

    def test_unregistered_package_is_reported(self, sample_tree: Path, tmp_path: Path) -> None:
        """Пакет модуля вне реестра, забытая секция `alembic.ini` и битая секция обнаруживаются."""
        # - Arrange -
        tree = tmp_path / "service"
        shutil.copytree(sample_tree, tree, ignore=IGNORED)
        (tree / "app" / "modules" / "rogue").mkdir()
        (tree / "app" / "modules" / "rogue" / "__init__.py").write_text('"""Модуль вне реестра."""\n')
        alembic_ini = tree / "alembic.ini"
        alembic_ini.write_text(
            alembic_ini.read_text(encoding="utf-8").replace(
                "version_locations = app/modules/identity/migrations/versions",
                "version_locations = app/modules/llm_gateway/migrations/versions",
            ),
            encoding="utf-8",
        )

        # - Act -
        violations = checks.registry_completeness_violations(tree)

        # - Assert -
        assert "rogue: есть в каталогах app/modules, нет в MODULES" in violations
        assert any(v.startswith("alembic.ini [identity]: version_locations") for v in violations)


@pytest.mark.req("SYS-01-R4")
class TestImportLinterLayersMatchSys01:
    """Строки `layers` контракта 2 совпадают с таблицей 3.3 SYS-01, ограниченной модулями реестра."""

    def test_sys01_table_is_parsed(self, sys01_layers: list[list[str]]) -> None:
        """Таблица 3.3 разбирается: верхняя строка `promotion`, нижняя `audit`, модули одной строки — через `|`."""
        # - Assert -
        assert sys01_layers[0] == ["promotion"]
        assert sys01_layers[-1] == ["audit"]
        assert ["lessons", "memorization"] in sys01_layers
        assert sys01_layers.index(["llm_gateway"]) < sys01_layers.index(["identity", "languages"])

    def test_current_tree(self, sys01_layers: list[list[str]]) -> None:
        """Контракт текущего дерева совпадает с картой (пустой реестр — контракта нет)."""
        # - Act / Assert -
        assert checks.dependency_order_violations(checks.SERVICE_ROOT, sys01_layers) == []

    def test_sample_tree(self, sample_tree: Path, sys01_layers: list[list[str]]) -> None:
        """Скаффолдер строит слои по реестру: `llm_gateway` над `identity`, как в SYS-01."""
        # - Act / Assert -
        assert checks.dependency_order_violations(sample_tree, sys01_layers) == []

    def test_wrong_registry_order_is_reported(
        self, sample_tree: Path, tmp_path: Path, sys01_layers: list[list[str]]
    ) -> None:
        """Реестр в порядке, обратном карте, даёт контракт, противоречащий SYS-01."""
        # - Arrange -
        tree = tmp_path / "service"
        shutil.copytree(sample_tree, tree, ignore=IGNORED)
        registry = tree / "app" / "modules" / "registry.py"
        registry.write_text(
            registry.read_text(encoding="utf-8").replace(
                '    "identity",\n    "llm_gateway",\n', '    "llm_gateway",\n    "identity",\n'
            ),
            encoding="utf-8",
        )
        run_in_tree(tree, "-m", "cli", "add-module", "llm_gateway")  # перегенерация блока контрактов

        # - Act -
        violations = checks.dependency_order_violations(tree, sys01_layers)

        # - Assert -
        assert len(violations) == 1
        assert "modules-dependency-order" in violations[0]


@pytest.mark.req("SYS-01-R1")
def test_registry_modules_are_in_sys01_map() -> None:
    """Каждый модуль реестра есть в таблице 3.1 SYS-01 (модуль вне карты не подключается)."""
    # - Arrange -
    sys01_modules = checks.parse_sys01_modules()

    # - Act -
    unknown = [name for name in checks.read_registry(checks.SERVICE_ROOT) if name not in sys01_modules]

    # - Assert -
    assert len(sys01_modules) == 23
    assert sys01_modules["identity"] == 1
    assert sys01_modules["llm_gateway"] == 1
    assert unknown == []


@pytest.mark.req("SYS-01-R10")
class TestCorePackagesInAllowlist:
    """Каталоги и модули первого уровня `app/core` (и подпакеты `app/core/dao`) — из allowlist SYS-01-R10."""

    def test_current_tree(self) -> None:
        """Текущий shared kernel укладывается в allowlist."""
        # - Act / Assert -
        assert checks.core_allowlist_violations(checks.SERVICE_ROOT) == []

    def test_unknown_package_is_reported(self, sample_tree: Path, tmp_path: Path) -> None:
        """Новый подпакет `app/core/utils` и модуль `app/core/dao/helpers.py` вне allowlist обнаруживаются."""
        # - Arrange -
        tree = tmp_path / "service"
        shutil.copytree(sample_tree, tree, ignore=IGNORED)
        (tree / "app" / "core" / "utils").mkdir()
        (tree / "app" / "core" / "dao" / "helpers.py").write_text('"""Вне allowlist."""\n')

        # - Act -
        violations = checks.core_allowlist_violations(tree)

        # - Assert -
        assert violations == [
            "app/core/utils: нет в allowlist SYS-01-R10",
            "app/core/dao/helpers.py: нет в allowlist SYS-01-R10",
        ]
