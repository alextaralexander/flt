"""Проверки архитектурных тестов: чистые функции, которые возвращают список нарушений.

- Файловые проверки (`root` — корень сервиса) разбирают исходники (AST, ini, markdown) без
  импорта приложения, поэтому применимы и к текущему дереву, и к его копии с модулями,
  сгенерированными скаффолдером.
- Проверки описаний модулей (`ModuleDefinition`) работают с импортированным приложением; для
  копии дерева их выполняет `python -m tests.architecture.checks` в отдельном процессе и
  печатает JSON-отчёт после строки-маркера `REPORT_MARKER`.

Пустой список — проверка пройдена; каждая строка списка описывает одно нарушение.
"""

import ast
import configparser
import fnmatch
import json
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from sqlalchemy import DateTime, Integer, Table, Uuid
from sqlalchemy.orm import DeclarativeBase
from starlette.routing import BaseRoute

from app.core.modules import ModuleDefinition
from app.core.security.security import access_declaration


SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVICE_ROOT.parents[2]
SYS01_PATH = REPO_ROOT / "Analytics" / "Specs" / "_system" / "SYS-01-module-map.md"
REPORT_MARKER = "@@ARCH-REPORT@@"

# Контракты 1–3 ADR-002 (раздел 3.5), которые скаффолдер генерирует по реестру.
CONTRACT_PUBLIC_API = "modules-public-api-only"
CONTRACT_DEPENDENCY_ORDER = "modules-dependency-order"
CONTRACT_INTERNAL_LAYERS = "module-internal-layers"
MODULE_CONTRACT_OPTIONS = {
    CONTRACT_PUBLIC_API: "modules",
    CONTRACT_DEPENDENCY_ORDER: "layers",
    CONTRACT_INTERNAL_LAYERS: "containers",
}

# Каталоги ревизий и общий env.py Alembic — не runtime-код инстанса (SYS-05-R3, R33).
MIGRATION_GLOBS = ("app/modules/*/migrations/*", "app/core/dao/db_helpers/migrations/*")

# SYS-01-R10: допустимые подпакеты и модули первого уровня `app/core` и подпакеты `app/core/dao`.
CORE_ALLOWLIST = frozenset(
    {
        "modules",
        "http",
        "schemas",
        "exceptions",
        "ids",
        "time",
        "dao",
        "kafka",
        "ws",
        "container",
        "security",
        "storage",
        "search",
        "mail",
        "captcha",
        "crypto",
        "i18n",
        "resilience",
        "extensions",
        "logging",
        "metrics",
        "telemetry",
        "health",
        "settings",
    }
)
CORE_DAO_ALLOWLIST = frozenset({"db_helpers", "caching"})

# SYS-06-R2: закрытый перечень действий кода права `<module>:<resource>:<action>`.
# Совпадает с `PERMISSION_ACTIONS` в `app/core/security/permissions.py` (появляется в Г.4).
PERMISSION_ACTIONS = frozenset(
    {
        "read",
        "create",
        "update",
        "delete",
        "publish",
        "unpublish",
        "start",
        "send",
        "invite",
        "join",
        "leave",
        "grant",
        "revoke",
        "suspend",
        "restrict",
        "moderate",
        "export",
        "use",
        "manage",
        "accept",
        "adjust",
        "approve",
        "archive",
        "claim",
        "confirm",
        "decide",
        "decline",
        "disable",
        "download",
        "enable",
        "finish",
        "hide",
        "install",
        "invite_tutor",
        "lift_restriction",
        "login",
        "logout",
        "logout_all",
        "mute",
        "poll",
        "read_any",
        "read_course_content",
        "read_draft",
        "read_public",
        "refresh",
        "regenerate",
        "register",
        "reject",
        "remove",
        "resolve",
        "restore",
        "search",
        "select",
        "test",
        "unhide",
        "uninstall",
        "unsuspend",
    }
)
PERMISSION_CODE_RE = re.compile(r"^[a-z_]+:[a-z_]+:[a-z_]+$")

# SYS-05-R7: технические таблицы доставки — без обязательных колонок.
TECHNICAL_TABLES = frozenset({"outbox", "processed_events", "scheduled_runs", "alembic_version"})

# SYS-05-R2: декораторы кэша в памяти процесса.
CACHE_DECORATORS = frozenset(
    {"functools.lru_cache", "functools.cache", "functools.cached_property", "async_lru.alru_cache"}
)
# SYS-05-R1: конструкторы изменяемых контейнеров и методы, изменяющие объект на месте.
MUTABLE_CONSTRUCTORS = frozenset(
    {
        "dict",
        "list",
        "set",
        "collections.deque",
        "collections.defaultdict",
        "collections.OrderedDict",
        "collections.Counter",
    }
)
MUTATING_METHODS = frozenset(
    {"append", "update", "add", "pop", "extend", "insert", "setdefault", "clear", "remove", "discard", "popitem"}
)

# SYS-05-R14: команды обхода и очистки Redis; разрешены только в обёртке `ModuleRedis`.
REDIS_SCAN_COMMANDS = frozenset({"keys", "scan", "scan_iter", "flushdb", "flushall"})
MODULE_REDIS_FILE = "app/core/dao/caching/module_redis.py"

# SYS-05-R33: `alembic.command` — только у точки входа роли `migrate`.
ALEMBIC_COMMAND_ALLOWED_FILES = frozenset({"app/__main__.py"})
DDL_RE = re.compile(r"\b(CREATE|ALTER|DROP)\s+(TABLE|SCHEMA|INDEX)\b", re.IGNORECASE)
MIGRATE_ON_START_FILES = ("app", "configs", "envs", "Makefile", "Dockerfile", "Dockerfile-dev", ".env.template")

# SYS-05-R22: типы, которые не пересекают границу модуля в `Protocol` публичного API.
FORBIDDEN_PUBLIC_TYPES = frozenset({"AsyncSession", "Session"})
INTERNAL_IMPORT_RE = re.compile(r"^app\.modules\.[a-z0-9_]+\.(models|dao)(\.|$)")


# --- Общие помощники ----------------------------------------------------------


def module_kebab(name: str) -> str:
    """Сегмент пути REST модуля: `llm_gateway` → `llm-gateway` (SYS-03-R1)."""
    return name.replace("_", "-")


def rel_path(path: Path, root: Path) -> str:
    """Путь файла относительно корня сервиса в POSIX-форме."""
    return path.relative_to(root).as_posix()


def dotted_name(rel: str) -> str:
    """Имя Python-модуля по относительному пути: `app/core/x.py` → `app.core.x`."""
    parts = rel.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def iter_python_files(root: Path, *rel_dirs: str, exclude: Sequence[str] = MIGRATION_GLOBS) -> Iterator[Path]:
    """Python-файлы каталогов `rel_dirs` (рекурсивно, по алфавиту) без `__pycache__` и исключений."""
    for rel_dir in rel_dirs:
        base = root / rel_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = rel_path(path, root)
            if "__pycache__" in path.parts or any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
                continue
            yield path


def parse_file(path: Path) -> ast.Module:
    """AST файла."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def read_registry(root: Path) -> tuple[str, ...]:
    """`MODULES` из `app/modules/registry.py` без импорта приложения.

    Raises:
        ValueError: в файле нет присваивания `MODULES` кортежем строк.
    """
    tree = parse_file(root / "app" / "modules" / "registry.py")
    for node in tree.body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            if any(isinstance(t, ast.Name) and t.id == "MODULES" for t in targets) and node.value is not None:
                value = ast.literal_eval(node.value)
                if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                    return value
    raise ValueError("В app/modules/registry.py нет `MODULES: tuple[str, ...] = (...)`.")


def module_packages(root: Path) -> set[str]:
    """Каталоги доменных модулей `app/modules/<name>/`."""
    base = root / "app" / "modules"
    return {path.name for path in base.iterdir() if path.is_dir() and not path.name.startswith(("_", "."))}


def _read_ini(path: Path) -> configparser.ConfigParser:
    """Ini-файл без интерполяции (`%` в значениях — не подстановка)."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return parser


def _ini_lines(value: str) -> list[str]:
    """Непустые строки многострочного значения ini без комментариев."""
    return [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith((";", "#"))]


def importlinter_module_rows(root: Path) -> dict[str, list[list[str]]]:
    """Модули контрактов 1–3 `.importlinter` по строкам: `{contract_id: [[module, ...], ...]}`.

    Для `layers` строка может содержать несколько модулей через `|`; скобки необязательного
    слоя `(name)` снимаются; префикс `app.modules.` отбрасывается.
    """
    parser = _read_ini(root / ".importlinter")
    rows: dict[str, list[list[str]]] = {}
    for contract, option in MODULE_CONTRACT_OPTIONS.items():
        section = f"importlinter:contract:{contract}"
        if not parser.has_option(section, option):
            continue
        rows[contract] = [
            [name.strip().strip("()").removeprefix("app.modules.") for name in line.split("|")]
            for line in _ini_lines(parser.get(section, option))
        ]
    return rows


def alembic_module_sections(root: Path) -> dict[str, Mapping[str, str]]:
    """Секции модулей `alembic.ini` (с параметром `flt_module`)."""
    parser = _read_ini(root / "alembic.ini")
    return {name: dict(parser[name]) for name in parser.sections() if parser.has_option(name, "flt_module")}


# --- Реестр, контракты и карта модулей (ADR-002 §3.5, SYS-01) -------------------


def registry_completeness_violations(root: Path) -> list[str]:
    """Каталоги `app/modules`, `MODULES`, контракты 1–3 `.importlinter` и секции `alembic.ini` совпадают."""
    registry = read_registry(root)
    violations = [f"{name}: повторяется в MODULES" for name in sorted({n for n in registry if registry.count(n) > 1})]
    sections = alembic_module_sections(root)
    sources: dict[str, set[str]] = {
        "каталогах app/modules": module_packages(root),
        "alembic.ini": set(sections),
    }
    contract_rows = importlinter_module_rows(root)
    for contract in MODULE_CONTRACT_OPTIONS:
        sources[f".importlinter ({contract})"] = {name for row in contract_rows.get(contract, []) for name in row}

    registered = set(registry)
    for source, names in sources.items():
        violations += [f"{name}: есть в MODULES, нет в {source}" for name in sorted(registered - names)]
        violations += [f"{name}: есть в {source}, нет в MODULES" for name in sorted(names - registered)]

    for name, options in sorted(sections.items()):
        expected = {
            "flt_module": name,
            "script_location": "app/core/dao/db_helpers/migrations",
            "version_locations": f"app/modules/{name}/migrations/versions",
        }
        violations += [
            f"alembic.ini [{name}]: {key} = {options.get(key)!r}, ожидается {value!r}"
            for key, value in expected.items()
            if options.get(key) != value
        ]
    return violations


def _markdown_section(text: str, heading_prefix: str) -> list[str]:
    """Строки раздела markdown от заголовка `heading_prefix` до следующего заголовка."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(heading_prefix):
            section: list[str] = []
            for body_line in lines[index + 1 :]:
                if body_line.startswith("#"):
                    break
                section.append(body_line)
            return section
    raise ValueError(f"Раздел {heading_prefix!r} не найден.")


def _table_rows(lines: Iterable[str]) -> list[list[str]]:
    """Строки данных markdown-таблицы (без заголовка и разделителя); экранированный `|` в ячейке сохраняется."""
    table = [line.strip() for line in lines if line.strip().startswith("|")]
    rows = [[cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]] for line in table]
    return [row for row in rows[1:] if not all(set(cell) <= {"-", ":", " "} for cell in row)]


def parse_sys01_layers(path: Path = SYS01_PATH) -> list[list[str]]:
    """Строки таблицы 3.3 SYS-01 сверху вниз: модули каждой строки `layers` контракта 2."""
    text = path.read_text(encoding="utf-8")
    rows = _table_rows(_markdown_section(text, "### 3.3."))
    return [[name.strip() for name in row[1].replace("`", "").split("\\|")] for row in rows]


def parse_sys01_modules(path: Path = SYS01_PATH) -> dict[str, int]:
    """Модули таблицы 3.1 SYS-01 и этап их появления."""
    text = path.read_text(encoding="utf-8")
    rows = _table_rows(_markdown_section(text, "### 3.1."))
    return {row[0].strip("`"): int(row[1]) for row in rows if row[0].startswith("`")}


def dependency_order_violations(root: Path, sys01_layers: Sequence[Sequence[str]]) -> list[str]:
    """Строки `layers` контракта 2 совпадают с таблицей 3.3 SYS-01, ограниченной модулями реестра (SYS-01-R4)."""
    registered = set(read_registry(root))
    expected = [sorted(name for name in row if name in registered) for row in sys01_layers]
    expected = [row for row in expected if row]
    actual = [sorted(row) for row in importlinter_module_rows(root).get(CONTRACT_DEPENDENCY_ORDER, [])]
    violations = []
    if actual != expected:
        violations.append(f"layers контракта {CONTRACT_DEPENDENCY_ORDER}: {actual}, по SYS-01 (3.3): {expected}")
    parser = _read_ini(root / ".importlinter")
    section = f"importlinter:contract:{CONTRACT_DEPENDENCY_ORDER}"
    if registered and parser.get(section, "exhaustive", fallback="false").strip().lower() != "true":
        violations.append(f"контракт {CONTRACT_DEPENDENCY_ORDER} без exhaustive = true")
    return violations


def core_allowlist_violations(root: Path) -> list[str]:
    """Подпакеты и модули первого уровня `app/core` и подпакеты `app/core/dao` — из allowlist SYS-01-R10."""
    violations = []
    for rel_dir, allowed in (("app/core", CORE_ALLOWLIST), ("app/core/dao", CORE_DAO_ALLOWLIST)):
        for entry in sorted((root / rel_dir).iterdir()):
            if entry.name.startswith(("_", ".")):
                continue
            if entry.is_dir() or entry.suffix == ".py":
                name = entry.stem if entry.is_file() else entry.name
                if name not in allowed:
                    violations.append(f"{rel_dir}/{entry.name}: нет в allowlist SYS-01-R10")
    return violations


# --- AST-проверки исходников ----------------------------------------------------


def walk_in_order(tree: ast.AST) -> list[ast.AST]:
    """Узлы дерева с позицией в порядке строк и столбцов исходника (нарушения — по порядку файла)."""
    return sorted(
        (node for node in ast.walk(tree) if hasattr(node, "lineno")),
        key=lambda node: (node.lineno, node.col_offset),
    )


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """Локальные имена импортов файла → полные имена (`lc` → `functools.lru_cache`, `ft` → `functools`)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def expr_dotted(node: ast.expr) -> str | None:
    """Точечное имя выражения `a.b.c` (без вызовов и индексов) или None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = expr_dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _resolve(name: str | None, aliases: Mapping[str, str]) -> str | None:
    """Полное имя по таблице импортов: первый сегмент заменяется на импортированное имя."""
    if name is None:
        return None
    head, _, tail = name.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{tail}" if tail else resolved


def _qualified_functions(tree: ast.Module) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Функции и методы файла с квалифицированными именами внутри файла (`Class.method`)."""

    def visit(body: list[ast.stmt], prefix: str) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield f"{prefix}{node.name}", node
                yield from visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, ast.ClassDef):
                yield from visit(node.body, f"{prefix}{node.name}.")

    yield from visit(tree.body, "")


def functools_cache_violations(root: Path, allowed: Iterable[str] = ()) -> list[str]:
    """Кэши `functools`/`async_lru` в памяти процесса (SYS-05-R2).

    В `app/modules` любое вхождение — нарушение; в остальном `app/` и в `configs/` —
    если полного имени функции нет в allowlist (SYS-05, раздел 6).
    """
    allowed_names = set(allowed)
    violations = []
    for path in iter_python_files(root, "app", "configs"):
        rel = rel_path(path, root)
        tree = parse_file(path)
        aliases = _import_aliases(tree)
        for qualname, function in _qualified_functions(tree):
            for decorator in function.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                resolved = _resolve(expr_dotted(target), aliases)
                if resolved not in CACHE_DECORATORS:
                    continue
                full_name = f"{dotted_name(rel)}.{qualname}"
                if rel.startswith("app/modules/") or full_name not in allowed_names:
                    violations.append(f"{rel}:{function.lineno}: @{resolved} на {full_name}")
    return violations


def _is_final(annotation: ast.expr | None) -> bool:
    """Аннотация `Final` или `Final[...]` (в том числе `typing.Final`)."""
    if annotation is None:
        return False
    node = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    dotted = expr_dotted(node)
    return dotted is not None and dotted.split(".")[-1] == "Final"


def _is_empty_mutable(value: ast.expr | None, aliases: Mapping[str, str]) -> bool:
    """Литерал `{}`/`[]` или вызов конструктора изменяемого контейнера (`dict()`, `collections.deque()` и т.п.)."""
    if isinstance(value, ast.Dict):
        return not value.keys
    if isinstance(value, ast.List):
        return not value.elts
    if isinstance(value, ast.Call):
        return _resolve(expr_dotted(value.func), aliases) in MUTABLE_CONSTRUCTORS
    return False


def module_state_violations(root: Path, allowed: Iterable[tuple[str, str]] = ()) -> list[str]:
    """Изменяемое состояние уровня модуля Python в `app/` (SYS-05-R1).

    Нарушение — пустой изменяемый контейнер на уровне модуля или имя уровня модуля без `Final`,
    которое функции файла изменяют (`global`, присваивание по индексу, `append`/`update`/`add`/`pop` и т.п.).
    Исключения — пары (файл, имя) из allowlist (SYS-05, раздел 6).
    """
    allowed_pairs = set(allowed)
    violations = []
    for path in iter_python_files(root, "app"):
        rel = rel_path(path, root)
        tree = parse_file(path)
        aliases = _import_aliases(tree)
        module_names: dict[str, ast.stmt] = {}
        final_names: set[str] = set()
        reasons: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                module_names[node.target.id] = node
                if _is_final(node.annotation):
                    final_names.add(node.target.id)
                if _is_empty_mutable(node.value, aliases):
                    reasons.setdefault(node.target.id, "изменяемый контейнер уровня модуля")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_names[target.id] = node
                        if _is_empty_mutable(node.value, aliases):
                            reasons.setdefault(target.id, "изменяемый контейнер уровня модуля")

        for _, function in _qualified_functions(tree):
            for node in ast.walk(function):
                mutated: list[str] = []
                if isinstance(node, ast.Global):
                    mutated += node.names
                elif isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign | ast.Delete):
                    targets = node.targets if isinstance(node, ast.Assign | ast.Delete) else [node.target]
                    mutated += [
                        t.value.id for t in targets if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                    ]
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in MUTATING_METHODS
                    and isinstance(node.func.value, ast.Name)
                ):
                    mutated.append(node.func.value.id)
                for name in mutated:
                    if name in module_names and name not in final_names:
                        reasons.setdefault(name, "изменяется в функциях файла")

        for name, reason in sorted(reasons.items()):
            if (rel, name) not in allowed_pairs:
                violations.append(f"{rel}:{module_names[name].lineno}: {name} — {reason}")
    return violations


def module_state_names(root: Path) -> set[tuple[str, str]]:
    """Все пары (файл, имя уровня модуля) в `app/` — для проверки, что allowlist не ссылается на пустоту."""
    pairs: set[tuple[str, str]] = set()
    for path in iter_python_files(root, "app"):
        rel = rel_path(path, root)
        for node in parse_file(path).body:
            targets = [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
            pairs |= {(rel, t.id) for t in targets if isinstance(t, ast.Name)}
    return pairs


def function_names(root: Path) -> set[str]:
    """Полные имена всех функций и методов `app/` и `configs/` — для проверки allowlist кэшей."""
    names: set[str] = set()
    for path in iter_python_files(root, "app", "configs"):
        module = dotted_name(rel_path(path, root))
        names |= {f"{module}.{qualname}" for qualname, _ in _qualified_functions(parse_file(path))}
    return names


def redis_command_violations(root: Path) -> list[str]:
    """Вызовы `keys`, `scan`, `scan_iter`, `flushdb`, `flushall` вне `ModuleRedis` (SYS-05-R14)."""
    violations = []
    for path in iter_python_files(root, "app"):
        rel = rel_path(path, root)
        if rel == MODULE_REDIS_FILE:
            continue
        for node in walk_in_order(parse_file(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in REDIS_SCAN_COMMANDS
                # у Redis `KEYS` шаблон обязателен: `dict.keys()` без аргументов — не нарушение (SYS-05-R14)
                and not (node.func.attr == "keys" and not node.args and not node.keywords)
            ):
                violations.append(f"{rel}:{node.lineno}: вызов .{node.func.attr}()")
    return violations


def module_redis_prefix_violations(root: Path) -> list[str]:
    """`ModuleRedis(prefix=...)` в модуле получает литерал, равный имени пакета модуля (ADR-002, SYS-05-R11)."""
    violations = []
    for module in sorted(module_packages(root)):
        for path in iter_python_files(root, f"app/modules/{module}"):
            rel = rel_path(path, root)
            for node in walk_in_order(parse_file(path)):
                if not isinstance(node, ast.Call):
                    continue
                dotted = expr_dotted(node.func)
                if dotted is None or dotted.split(".")[-1] != "ModuleRedis":
                    continue
                prefix_nodes = [kw.value for kw in node.keywords if kw.arg == "prefix"] or node.args[:1]
                prefix = prefix_nodes[0] if prefix_nodes else None
                if not (isinstance(prefix, ast.Constant) and prefix.value == module):
                    shown = ast.unparse(prefix) if prefix is not None else "<нет>"
                    violations.append(f"{rel}:{node.lineno}: ModuleRedis(prefix={shown}), ожидается {module!r}")
    return violations


def broker_publish_violations(root: Path) -> list[str]:
    """Прямая публикация в Kafka из модулей: `broker.publish`, `<router>.publisher`, доступ к `.broker` (ADR-004)."""
    violations = []
    for path in iter_python_files(root, "app/modules"):
        rel = rel_path(path, root)
        for node in walk_in_order(parse_file(path)):
            if not isinstance(node, ast.Attribute):
                continue
            receiver = expr_dotted(node.value) or ""
            terminal = receiver.split(".")[-1].lower()
            if node.attr == "broker" or (
                node.attr in {"publish", "publisher"} and ("broker" in terminal or "router" in terminal)
            ):
                violations.append(f"{rel}:{node.lineno}: {receiver}.{node.attr}")
    return violations


def _top_level_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Операторы уровня модуля, включая тела `if`/`try` (импорты под `TYPE_CHECKING`), без тел функций."""
    for node in body:
        yield node
        if isinstance(node, ast.If | ast.Try):
            yield from _top_level_statements(node.body + node.orelse + getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                yield from _top_level_statements(handler.body)


def _absolute_module(node: ast.ImportFrom, rel: str) -> str:
    """Абсолютное имя модуля `from ... import` с учётом относительного импорта."""
    if node.level == 0:
        return node.module or ""
    package = dotted_name(rel).split(".")
    if not rel.endswith("__init__.py"):
        package = package[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _imported_modules(node: ast.Import | ast.ImportFrom, rel: str) -> list[tuple[str, str]]:
    """Пары (полное имя импортируемого объекта или модуля, локальное имя) оператора импорта."""
    if isinstance(node, ast.Import):
        return [(alias.name, alias.asname or alias.name.split(".")[0]) for alias in node.names]
    module = _absolute_module(node, rel)
    return [(f"{module}.{alias.name}", alias.asname or alias.name) for alias in node.names]


def _annotation_names(annotation: ast.expr | None) -> set[str]:
    """Идентификаторы, упомянутые в аннотации (включая строковые аннотации)."""
    if annotation is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                names |= _annotation_names(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                continue
    return names


def _is_protocol(node: ast.ClassDef) -> bool:
    """Класс наследует `typing.Protocol`."""
    return any((expr_dotted(base) or "").split(".")[-1] == "Protocol" for base in node.bases)


def public_api_violations(root: Path) -> list[str]:
    """Публичный API модулей не экспортирует модели и DAO и не передаёт сессии через границу.

    - ADR-002 `test_module_public_exports_only_contracts`: в `public/` нет импортов уровня модуля
      из `app.modules.<m>.models` и `app.modules.<m>.dao` (фабрика `Depends()` может импортировать
      реализацию внутри своей функции).
    - SYS-05-R22: методы `Protocol` в `public/` не принимают и не возвращают `AsyncSession`,
      `Session` и модели SQLAlchemy модулей.
    """
    violations = []
    for module in sorted(module_packages(root)):
        for path in iter_python_files(root, f"app/modules/{module}/public"):
            rel = rel_path(path, root)
            tree = parse_file(path)
            model_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import | ast.ImportFrom):
                    for imported, local in _imported_modules(node, rel):
                        if INTERNAL_IMPORT_RE.match(imported) and ".models" in imported:
                            model_names.add(local)
            for node in _top_level_statements(tree.body):
                if isinstance(node, ast.Import | ast.ImportFrom):
                    for imported, _ in _imported_modules(node, rel):
                        if INTERNAL_IMPORT_RE.match(imported):
                            violations.append(f"{rel}:{node.lineno}: public импортирует {imported}")
            for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and _is_protocol(n)):
                for method in (n for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
                    arguments = method.args
                    annotations = [
                        a.annotation
                        for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
                        + [a for a in (arguments.vararg, arguments.kwarg) if a is not None]
                    ] + [method.returns]
                    used = set().union(*(_annotation_names(a) for a in annotations))
                    for name in sorted(used & (FORBIDDEN_PUBLIC_TYPES | model_names)):
                        violations.append(f"{rel}:{method.lineno}: {cls.name}.{method.name} использует {name}")
    return violations


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Идентификаторы (`id`) узлов-докстрингов модуля, классов и функций."""
    nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                nodes.add(id(first.value))
    return nodes


def runtime_ddl_violations(root: Path) -> list[str]:
    """DDL при старте инстанса (SYS-05-R33).

    В `app/` вне каталогов миграций нет импорта `alembic.op`, импорт `alembic.command` есть
    только у точки входа роли `migrate` (`app/__main__.py`), нет вызовов `create_all`/`drop_all`
    и строк SQL `CREATE|ALTER|DROP TABLE|SCHEMA|INDEX` (кроме докстрингов).
    """
    violations = []
    for path in iter_python_files(root, "app"):
        rel = rel_path(path, root)
        tree = parse_file(path)
        docstrings = _docstring_nodes(tree)
        for node in walk_in_order(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for imported, _ in _imported_modules(node, rel):
                    if imported.startswith("alembic.op") or (
                        imported.startswith("alembic.command") and rel not in ALEMBIC_COMMAND_ALLOWED_FILES
                    ):
                        violations.append(f"{rel}:{node.lineno}: импорт {imported}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"create_all", "drop_all"}:
                    violations.append(f"{rel}:{node.lineno}: вызов .{node.func.attr}()")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and DDL_RE.search(node.value)
            ):
                violations.append(f"{rel}:{node.lineno}: DDL в строке {node.value[:60]!r}")
    return violations


def migrate_on_start_violations(root: Path) -> list[str]:
    """Настройки `MIGRATE_ON_START` нет в коде, конфигурации и env-файлах сервиса (SYS-05-R33)."""
    violations = []
    for name in MIGRATE_ON_START_FILES:
        target = root / name
        files = sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else [target]
        for path in files:
            if not path.exists() or "__pycache__" in path.parts:
                continue
            if "MIGRATE_ON_START" in path.read_text(encoding="utf-8", errors="ignore"):
                violations.append(f"{rel_path(path, root)}: упоминает MIGRATE_ON_START")
    return violations


# --- Проверки описаний модулей (ModuleDefinition) -------------------------------


def iter_routes(routes: Sequence[BaseRoute]) -> Iterator[RouteContext]:
    """Действующие маршруты с полными путями, включая маршруты вложенных роутеров (`include_router`)."""
    yield from iter_route_contexts(routes)


def _foreign_schema(target_fullname: str, default_schema: str | None) -> str | None:
    """Схема цели внешнего ключа `schema.table.column` (без схемы — схема метаданных)."""
    parts = target_fullname.split(".")
    return parts[0] if len(parts) >= 3 else default_schema


def cross_schema_fk_violations(modules: Sequence[ModuleDefinition]) -> list[str]:
    """Внешние ключи таблиц модуля ведут только в его схему (ADR-002, SYS-01-R9)."""
    violations = []
    for module in modules:
        for table in module.metadata.tables.values():
            for fk in table.foreign_keys:
                schema = _foreign_schema(fk.target_fullname, module.metadata.schema)
                if schema != module.name:
                    violations.append(f"{module.name}: {table.fullname}.{fk.parent.name} → {fk.target_fullname}")
    return violations


def table_schema_violations(modules: Sequence[ModuleDefinition]) -> list[str]:
    """Все таблицы `module.metadata` лежат в схеме `module.name` (ADR-002, SYS-01-R8)."""
    return [
        f"{module.name}: таблица {table.fullname} в схеме {table.schema!r}"
        for module in modules
        for table in module.metadata.tables.values()
        if table.schema != module.name
    ]


def public_schema_violations(modules: Sequence[ModuleDefinition]) -> list[str]:
    """Ни одна таблица модулей не попадает в схему `public` или в схему по умолчанию (SYS-05-R7)."""
    return [
        f"{module.name}: таблица {table.name} в схеме public"
        for module in modules
        for table in module.metadata.tables.values()
        if table.schema in (None, "public")
    ]


def _mapped_classes() -> dict[Table, type]:
    """Таблица → декларативный класс модели (по всем наследникам `DeclarativeBase`)."""
    classes: dict[Table, type] = {}
    stack: list[type] = list(DeclarativeBase.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        table = cls.__dict__.get("__table__")
        if isinstance(table, Table):
            classes[table] = cls
    return classes


def _column_problems(table: Table) -> list[str]:
    """Расхождения таблицы с обязательными колонками SYS-05-R7."""
    columns = table.columns
    problems = []
    expectations: dict[str, tuple[str, Callable[[Any], bool]]] = {
        "id": ("uuid", lambda column: isinstance(column.type, Uuid)),
        "created_at": ("timestamptz", lambda column: isinstance(column.type, DateTime) and column.type.timezone),
        "updated_at": ("timestamptz", lambda column: isinstance(column.type, DateTime) and column.type.timezone),
        "version": ("integer", lambda column: isinstance(column.type, Integer)),
    }
    for name, (type_name, matches) in expectations.items():
        if name not in columns:
            problems.append(f"нет колонки {name}")
        elif not matches(columns[name]):
            problems.append(f"{name} не {type_name} ({columns[name].type})")
    if [column.name for column in table.primary_key.columns] != ["id"]:
        problems.append("первичный ключ не (id)")
    return problems


def mandatory_column_violations(modules: Sequence[ModuleDefinition]) -> list[str]:
    """У таблиц модулей есть `id uuid` (PK), `created_at`, `updated_at` (`timestamptz`), `version` (SYS-05-R7).

    Исключения: технические таблицы доставки и модели с `__flt_technical__ = True`.
    """
    classes = _mapped_classes()
    violations = []
    for module in modules:
        for table in module.metadata.tables.values():
            model = classes.get(table)
            if table.name in TECHNICAL_TABLES or getattr(model, "__flt_technical__", False):
                continue
            violations += [f"{module.name}: {table.fullname}: {problem}" for problem in _column_problems(table)]
    return violations


def settings_prefix_violations(modules: Sequence[ModuleDefinition]) -> list[str]:
    """`env_prefix` настроек модуля равен `<MODULE>_` (ADR-002, раздел 3.3)."""
    violations = []
    for module in modules:
        if module.settings is None:
            continue
        prefix = module.settings.model_config.get("env_prefix")
        if prefix != f"{module.name.upper()}_":
            violations.append(f"{module.name}: env_prefix {prefix!r}, ожидается {module.name.upper()}_")
    return violations


def permission_violations(
    modules: Sequence[ModuleDefinition], actions: Iterable[str] = PERMISSION_ACTIONS
) -> list[str]:
    """Коды прав `<module>:<resource>:<action>`: формат, владелец, действие из перечня, уникальность (SYS-06-R2)."""
    allowed_actions = set(actions)
    owners: dict[str, str] = {}
    violations = []
    for module in modules:
        for code in module.permissions:
            if not PERMISSION_CODE_RE.match(code):
                violations.append(f"{module.name}: код {code!r} не по формату <module>:<resource>:<action>")
                continue
            owner, _, action = code.split(":")
            if owner != module.name:
                violations.append(f"{module.name}: код {code!r} с чужим первым сегментом")
            if action not in allowed_actions:
                violations.append(f"{module.name}: действие {action!r} кода {code!r} нет в PERMISSION_ACTIONS")
            if code in owners:
                violations.append(f"{module.name}: код {code!r} уже объявлен модулем {owners[code]}")
            owners[code] = module.name
    return violations


def router_prefix_violations(
    modules: Sequence[ModuleDefinition], allowed_extra_prefixes: Mapping[str, tuple[str, ...]]
) -> list[str]:
    """Пути REST-роутера модуля — под `/api/v1/<module-kebab>` или разрешённым `extra_prefixes` (SYS-03-R1, R2)."""
    violations = []
    for module in modules:
        allowed = allowed_extra_prefixes.get(module.name, ())
        violations += [
            f"{module.name}: extra_prefixes {prefix!r} не разрешён (SYS-03, раздел 6)"
            for prefix in module.extra_prefixes
            if prefix not in allowed
        ]
        if module.router is None:
            continue
        base = f"/api/v1/{module_kebab(module.name)}"
        if module.router.prefix != base:
            violations.append(f"{module.name}: префикс роутера {module.router.prefix!r}, ожидается {base!r}")
        prefixes = (base, *module.extra_prefixes)
        for route in iter_routes(module.router.routes):
            path = route.path or ""
            if not any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes):
                violations.append(f"{module.name}: путь {path!r} вне {prefixes}")
    return violations


def _declares_access(dependant: Dependant) -> bool:
    """В дереве зависимостей есть `auth_user(...)`/`auth_user_optional(...)` с правом или маркер `public()`."""
    stack = list(dependant.dependencies)
    while stack:
        dependency = stack.pop()
        declaration = access_declaration(dependency.call)
        if declaration is not None and (declaration.permission or declaration.kind == "public"):
            return True
        stack.extend(dependency.dependencies)
    return False


def route_access_violations(modules: Sequence[ModuleDefinition]) -> list[str]:
    """Каждый REST-роут модуля объявляет право (`auth_user`, `auth_user_optional`) или `public()` (SYS-06-R5)."""
    violations = []
    for module in modules:
        if module.router is None:
            continue
        for route in iter_routes(module.router.routes):
            if isinstance(route.original_route, APIRoute) and not _declares_access(route.dependant):
                violations.append(f"{module.name}: {sorted(route.methods or ())} {route.path} не объявляет право")
    return violations


def definition_report(
    modules: Sequence[ModuleDefinition], allowed_extra_prefixes: Mapping[str, tuple[str, ...]]
) -> dict[str, list[str]]:
    """Результаты всех проверок описаний модулей: `{имя проверки: нарушения}`."""
    return {
        "cross_schema_fk": cross_schema_fk_violations(modules),
        "table_schema": table_schema_violations(modules),
        "public_schema": public_schema_violations(modules),
        "mandatory_columns": mandatory_column_violations(modules),
        "settings_prefix": settings_prefix_violations(modules),
        "permissions": permission_violations(modules),
        "router_prefix": router_prefix_violations(modules, allowed_extra_prefixes),
        "route_access": route_access_violations(modules),
    }


def main() -> int:
    """Печатает JSON-отчёт проверок описаний модулей реестра текущего дерева (для копии дерева в тестах)."""
    from app.core.modules import load_modules
    from app.modules.registry import MODULES
    from tests.architecture.conftest import ALLOWED_EXTRA_PREFIXES

    modules = load_modules(MODULES)
    report = {"modules": [module.name for module in modules], **definition_report(modules, ALLOWED_EXTRA_PREFIXES)}
    print(REPORT_MARKER + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
