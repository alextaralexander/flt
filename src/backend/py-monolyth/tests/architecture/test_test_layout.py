"""Каждый архитектурный тест несёт маркер `req` с существующим требованием SYS (SYS-10-R7, SYS-10-R8)."""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.architecture import checks


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R8")]

ARCHITECTURE_DIR = Path(__file__).parent
REQ_RE = re.compile(r"^SYS-(\d{2})-R\d+$")
SYSTEM_SPECS_DIR = checks.REPO_ROOT / "Analytics" / "Specs" / "_system"


def _req_values(decorators: list[ast.expr]) -> list[str]:
    """Значения `pytest.mark.req("...")` среди декораторов или элементов `pytestmark`."""
    values = []
    for node in decorators:
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            if (checks.expr_dotted(call.func) or "").endswith("mark.req") and call.args:
                argument = call.args[0]
                values.append(argument.value if isinstance(argument, ast.Constant) else ast.unparse(argument))
    return values


def _module_marks(tree: ast.Module) -> list[str]:
    """Маркеры `req` из `pytestmark` уровня файла."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            return _req_values([node.value])
    return []


def _tests_with_marks(path: Path) -> Iterator[tuple[str, list[str]]]:
    """Тестовые функции файла и их маркеры `req` (с учётом класса и `pytestmark`)."""
    tree = checks.parse_file(path)
    module_marks = _module_marks(tree)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
            yield node.name, module_marks + _req_values(node.decorator_list)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_marks = module_marks + _req_values(node.decorator_list)
            for method in node.body:
                if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) and method.name.startswith("test_"):
                    yield f"{node.name}.{method.name}", class_marks + _req_values(method.decorator_list)


def _requirement_exists(requirement: str) -> bool:
    """Требование объявлено заголовком `### SYS-NN-R<M> ...` в своей системной спецификации."""
    match = REQ_RE.match(requirement)
    if match is None:
        return False
    specs = list(SYSTEM_SPECS_DIR.glob(f"SYS-{match.group(1)}-*.md"))
    return any(f"### {requirement} " in spec.read_text(encoding="utf-8") for spec in specs)


def test_architecture_tests_have_req_marker() -> None:
    """У каждого теста `tests/architecture` есть маркер `req` с существующим требованием SYS-NN-R<M>."""
    # - Arrange -
    tests = {
        f"{path.name}::{name}": marks
        for path in sorted(ARCHITECTURE_DIR.glob("test_*.py"))
        for name, marks in _tests_with_marks(path)
    }

    # - Act -
    unmarked = sorted(name for name, marks in tests.items() if not marks)
    unknown = sorted({mark for marks in tests.values() for mark in marks if not _requirement_exists(mark)})

    # - Assert -
    assert len(tests) > 20
    assert unmarked == []
    assert unknown == []


def test_unknown_requirement_is_rejected() -> None:
    """Несуществующее требование и неверный формат не принимаются."""
    assert _requirement_exists("SYS-05-R33")
    assert not _requirement_exists("SYS-05-R999")
    assert not _requirement_exists("STU-12.1-AC3")
