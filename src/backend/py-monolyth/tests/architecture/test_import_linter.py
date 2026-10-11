"""Контракты границ import-linter выполняются, а их нарушение ломает сборку (ADR-002 §3.5–3.6).

`test_boundary_violation_breaks_build` — критерий выхода этапа 1 (SDD_plan.md): в копию дерева
с модулями-образцами дописывается импорт через границу, и `lint-imports` (то же, что `make arch`)
обязан завершиться с ошибкой и назвать нарушенный контракт.
"""

import configparser
import shutil
from pathlib import Path

import pytest

from tests.architecture.checks import SERVICE_ROOT
from tests.architecture.conftest import IGNORED, run_in_tree


pytestmark = pytest.mark.no_db

# Сценарий: (id контракта, файл-зонд в копии дерева, его содержимое).
VIOLATIONS = [
    pytest.param(
        "modules-public-api-only",
        "app/modules/identity/services/_probe.py",
        "import app.modules.llm_gateway.dao\n",
        id="internal-package-of-other-module",
    ),
    pytest.param(
        "modules-dependency-order",
        "app/modules/identity/services/_probe.py",
        "import app.modules.llm_gateway.public\n",
        id="lower-module-imports-upper-public",
    ),
    pytest.param(
        "module-internal-layers",
        "app/modules/llm_gateway/models/_probe.py",
        "import app.modules.llm_gateway.services\n",
        id="models-import-services",
    ),
    pytest.param(
        "core-does-not-import-modules",
        "app/core/_probe.py",
        "import app.modules.identity.public\n",
        id="core-imports-module",
    ),
    pytest.param(
        "redis-only-via-module-redis",
        "app/modules/identity/services/_probe.py",
        "import redis\n",
        id="module-imports-redis",
    ),
    pytest.param(
        "kafka-publish-only-via-outbox",
        "app/modules/identity/services/_probe.py",
        "import app.core.kafka.broker\n",
        id="module-imports-broker",
    ),
    pytest.param(
        "storage-clients-only-via-core",
        "app/modules/identity/services/_probe.py",
        "import opensearchpy\n",
        id="module-imports-search-client",
    ),
]


def _contract_names(tree: Path) -> dict[str, str]:
    """Идентификатор контракта → человекочитаемое имя из `.importlinter` (его печатает `lint-imports`)."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(tree / ".importlinter", encoding="utf-8")
    prefix = "importlinter:contract:"
    return {
        section.removeprefix(prefix): parser[section]["name"]
        for section in parser.sections()
        if section.startswith(prefix)
    }


@pytest.mark.req("SYS-01-R5")
@pytest.mark.req("SYS-12-R13")
def test_import_linter_passes() -> None:
    """Все контракты `.importlinter` выполняются на текущем дереве."""
    # - Act -
    result = run_in_tree(SERVICE_ROOT, tool="lint-imports", check=False)

    # - Assert -
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


@pytest.mark.req("SYS-01-R5")
@pytest.mark.req("SYS-12-R13")
def test_import_linter_passes_with_sample_modules(sample_tree: Path) -> None:
    """Контракты 1–7 (с блоком модулей) выполняются на дереве с модулями-образцами скаффолдера."""
    # - Act -
    result = run_in_tree(sample_tree, tool="lint-imports", check=False)

    # - Assert -
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(_contract_names(sample_tree)) >= {param.values[0] for param in VIOLATIONS}
    assert "0 broken" in result.stdout


@pytest.mark.req("SYS-01-R5")
@pytest.mark.req("SYS-12-R13")
@pytest.mark.parametrize(("contract", "probe", "source"), VIOLATIONS)
def test_boundary_violation_breaks_build(
    sample_tree: Path, tmp_path: Path, contract: str, probe: str, source: str
) -> None:
    """Импорт через границу модуля ломает `lint-imports` и называет нарушенный контракт."""
    # - Arrange -
    tree = tmp_path / "service"
    shutil.copytree(sample_tree, tree, ignore=IGNORED)
    (tree / probe).write_text(f'"""Зонд нарушения границы."""\n\n{source}', encoding="utf-8")
    contract_name = _contract_names(tree)[contract]

    # - Act -
    result = run_in_tree(tree, tool="lint-imports", check=False)

    # - Assert -
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BROKEN" in result.stdout
    broken_lines = [line for line in result.stdout.splitlines() if " BROKEN" in line]
    assert any(line.startswith(contract_name) for line in broken_lines), result.stdout
