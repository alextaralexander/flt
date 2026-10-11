"""Typer-скаффолдер модулей монолита (ADR-002, раздел 3.7).

Примеры::

    python -m cli add-module identity
    python -m cli add-entity User --module identity
    python -m cli add-subscriber USER_DELETED "flt.identity.user_deleted.v1" --module notifications
    python -m cli list-modules
    python -m cli add-entity Order --module identity --dry-run

Выпуск dev-токенов (`issue-token`) возвращается на этапе 1 Г.5 поверх `TokenIssuer` модуля
`identity` (ADR-006); симметричный ключ boilerplate удалён (ADR-013).

Скаффолдер не перезаписывает существующие файлы и идемпотентен по вставкам
(повторный запуск не дублирует импорты, строки роутера, секции и члены enum).
Сгенерированный код обязан проходить `make check` без правок.
"""

# Вызываем только ruff с фиксированными аргументами, без shell.
import ast
import subprocess  # nosec B404
import sys
from pathlib import Path

import typer

from cli import templates
from cli.naming import (
    is_valid_module_name,
    is_valid_topic,
    to_const,
    to_kebab,
    to_pascal,
    to_snake,
)


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = "app/modules/registry.py"
ALEMBIC_INI_PATH = "alembic.ini"
IMPORTLINTER_PATH = ".importlinter"
STANDS = ("local", "dev", "test", "prod")

app = typer.Typer(
    add_completion=False,
    help="Скаффолдер монолита: модули, REST-сущности, Kafka-консьюмеры, список модулей.",
)


# --- Файловые операции ------------------------------------------------------


def _create_file(rel_path: str, content: str, dry_run: bool) -> None:
    """Создать файл. Существующий файл не перезаписывается."""
    path = ROOT / rel_path
    if path.exists():
        typer.secho(f"  = пропуск (уже существует): {rel_path}", fg=typer.colors.YELLOW)
        return
    if dry_run:
        typer.secho(f"  + [dry-run] создал бы: {rel_path}", fg=typer.colors.CYAN)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    typer.secho(f"  + создан: {rel_path}", fg=typer.colors.GREEN)


def _append_file(rel_path: str, snippet: str, marker: str, dry_run: bool) -> None:
    """Дописать snippet в конец файла, если marker в нём ещё не встречается."""
    path = ROOT / rel_path
    text = path.read_text(encoding="utf-8")
    if marker in text:
        typer.secho(f"  = пропуск (уже подключено): {rel_path}", fg=typer.colors.YELLOW)
        return
    if dry_run:
        typer.secho(f"  ~ [dry-run] дописал бы в конец: {rel_path}", fg=typer.colors.CYAN)
        return
    path.write_text(text.rstrip("\n") + "\n" + snippet, encoding="utf-8")
    typer.secho(f"  ~ обновлён: {rel_path}", fg=typer.colors.GREEN)


def _insert_after(rel_path: str, anchor: str, snippet: str, marker: str, dry_run: bool) -> None:
    """Вставить snippet сразу после строки, содержащей anchor (если marker отсутствует).

    Raises:
        typer.Exit: якорь не найден — сгенерированный код был бы неполным.
    """
    path = ROOT / rel_path
    text = path.read_text(encoding="utf-8")
    if marker in text:
        typer.secho(f"  = пропуск (уже есть): {rel_path}", fg=typer.colors.YELLOW)
        return
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if anchor in line:
            if dry_run:
                typer.secho(f"  ~ [dry-run] вставил бы в: {rel_path}", fg=typer.colors.CYAN)
                return
            lines.insert(idx + 1, snippet)
            path.write_text("".join(lines), encoding="utf-8")
            typer.secho(f"  ~ обновлён: {rel_path}", fg=typer.colors.GREEN)
            return
    typer.secho(f"  ! якорь не найден в {rel_path}: '{anchor}'", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _format(rel_paths: list[str], dry_run: bool) -> None:
    """Привести затронутые Python-файлы к стилю проекта (ruff: сортировка импортов + формат)."""
    if dry_run:
        return
    existing = [str(ROOT / p) for p in rel_paths if p.endswith(".py") and (ROOT / p).exists()]
    if not existing:
        return
    for args in (["check", "--select", "I", "--fix", "--quiet"], ["format", "--quiet"]):
        try:
            # Фиксированный инструмент, аргументы не из пользовательского ввода.
            subprocess.run(  # nosec B603
                [sys.executable, "-m", "ruff", *args, *existing],
                cwd=ROOT,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            typer.secho("  ! ruff недоступен — запусти 'make format' вручную", fg=typer.colors.YELLOW)
            return
    typer.secho("  ✓ применён ruff (импорты + формат) к затронутым файлам", fg=typer.colors.GREEN)


# --- Реестр модулей ---------------------------------------------------------


def read_registry() -> tuple[str, ...]:
    """Прочитать `MODULES` из `app/modules/registry.py` без импорта приложения.

    Raises:
        typer.Exit: в файле нет присваивания `MODULES` кортежем строк.
    """
    tree = ast.parse((ROOT / REGISTRY_PATH).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MODULES":
            value = ast.literal_eval(node.value) if node.value is not None else None
            if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                return value
    typer.secho(f"  ! в {REGISTRY_PATH} нет `MODULES: tuple[str, ...] = (...)`", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _write_registry(modules: tuple[str, ...], dry_run: bool) -> None:
    """Перезаписать `registry.py` с новым списком модулей (порядок сохраняется)."""
    if dry_run:
        typer.secho(f"  ~ [dry-run] обновил бы: {REGISTRY_PATH}", fg=typer.colors.CYAN)
        return
    body = "(\n" + "".join(f'    "{name}",\n' for name in modules) + ")" if modules else "()"
    (ROOT / REGISTRY_PATH).write_text(templates.render(templates.REGISTRY, MODULES=body), encoding="utf-8")
    typer.secho(f"  ~ обновлён: {REGISTRY_PATH}", fg=typer.colors.GREEN)


def render_importlinter_modules(modules: tuple[str, ...]) -> str:
    """Текст контрактов 1–3 `.importlinter` для модулей реестра (пусто, если модулей нет)."""
    if not modules:
        return ""

    def as_list(names: list[str]) -> str:
        """Значения многострочного параметра ini с отступом."""
        return "\n".join(f"    {name}" for name in names)

    return templates.render(
        templates.IMPORTLINTER_MODULE_CONTRACTS,
        MODULES_LIST=as_list([f"app.modules.{name}" for name in modules]),
        LAYERS_LIST=as_list(list(reversed(modules))),
        CONTAINERS_LIST=as_list([f"app.modules.{name}" for name in modules]),
    )


def _write_importlinter(modules: tuple[str, ...], dry_run: bool) -> None:
    """Перегенерировать блок контрактов модулей в `.importlinter` между маркерами.

    Raises:
        typer.Exit: в файле нет маркеров блока модулей.
    """
    path = ROOT / IMPORTLINTER_PATH
    text = path.read_text(encoding="utf-8")
    begin, end = text.find(templates.IMPORTLINTER_BEGIN), text.find(templates.IMPORTLINTER_END)
    if begin == -1 or end == -1 or end < begin:
        typer.secho(f"  ! в {IMPORTLINTER_PATH} нет маркеров блока модулей", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    head = text[: begin + len(templates.IMPORTLINTER_BEGIN)]
    new_text = head + "\n" + render_importlinter_modules(modules) + text[end:]
    if new_text == text:
        typer.secho(f"  = пропуск (без изменений): {IMPORTLINTER_PATH}", fg=typer.colors.YELLOW)
        return
    if dry_run:
        typer.secho(f"  ~ [dry-run] обновил бы: {IMPORTLINTER_PATH}", fg=typer.colors.CYAN)
        return
    path.write_text(new_text, encoding="utf-8")
    typer.secho(f"  ~ обновлён: {IMPORTLINTER_PATH}", fg=typer.colors.GREEN)


def _module_tokens(module: str) -> dict[str, str]:
    """Токены шаблонов для имени модуля."""
    return {
        "MODULE": module,
        "MODULE_PASCAL": to_pascal(module),
        "MODULE_UPPER": module.upper(),
        "MODULE_KEBAB": to_kebab(module),
    }


def _require_module(module: str) -> None:
    """Проверить, что модуль уже создан скаффолдером.

    Raises:
        typer.Exit: модуля нет в реестре или нет его `module.py`.
    """
    if module not in read_registry() or not (ROOT / f"app/modules/{module}/module.py").exists():
        typer.secho(
            f"  ! модуль `{module}` не найден — сначала `make scaffold-module name={module}`",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)


# --- Команды ----------------------------------------------------------------


@app.command()
def add_module(
    name: str = typer.Argument(..., help="Имя модуля в snake_case, напр. identity или llm_gateway."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Только показать, что будет сделано."),
) -> None:
    """Создать модуль app/modules/<name> и зарегистрировать его (реестр, .importlinter, alembic.ini, envs, тесты)."""
    if not is_valid_module_name(name):
        typer.secho(f"  ! недопустимое имя модуля: {name!r} (snake_case, не зарезервировано)", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    tokens = _module_tokens(name)
    base = f"app/modules/{name}"
    typer.secho(f"\nМодуль: {name} (REST /api/v1/{tokens['MODULE_KEBAB']}, схема PostgreSQL {name})\n", bold=True)

    files = {
        f"{base}/__init__.py": templates.MODULE_INIT,
        f"{base}/module.py": templates.MODULE_DEFINITION,
        f"{base}/public/__init__.py": templates.MODULE_PUBLIC_INIT,
        f"{base}/public/topics.py": templates.MODULE_PUBLIC_TOPICS,
        f"{base}/models/__init__.py": templates.MODULE_MODELS_INIT,
        f"{base}/settings.py": templates.MODULE_SETTINGS,
        f"{base}/permissions.py": templates.MODULE_PERMISSIONS,
        f"{base}/api/__init__.py": templates.MODULE_API_INIT,
        f"{base}/api/router.py": templates.MODULE_ROUTER,
        f"{base}/migrations/versions/.gitkeep": "",
        "tests/modules/__init__.py": templates.MODULE_TESTS_PACKAGE_INIT,
        f"tests/modules/{name}/__init__.py": templates.MODULE_TESTS_INIT,
        f"tests/modules/{name}/conftest.py": templates.MODULE_TESTS_CONFTEST,
    }
    for layer in ("services", "dao", "schemas"):
        files[f"{base}/{layer}/__init__.py"] = templates.render(templates.MODULE_LAYER_INIT, LAYER=layer)
    for stand in STANDS:
        files[f"envs/{stand}/{name}_{stand}.env"] = templates.render(templates.MODULE_ENV_FILE, STAND=stand)
    for rel_path, template in files.items():
        _create_file(rel_path, templates.render(template, **tokens), dry_run)

    modules = read_registry()
    if name in modules:
        typer.secho(f"  = пропуск (уже в реестре): {REGISTRY_PATH}", fg=typer.colors.YELLOW)
    else:
        modules = (*modules, name)
        _write_registry(modules, dry_run)
    _write_importlinter(modules, dry_run)

    _append_file(
        ALEMBIC_INI_PATH,
        templates.render(templates.MODULE_ALEMBIC_SECTION, **tokens),
        marker=f"[{name}]",
        dry_run=dry_run,
    )

    _format([*files, REGISTRY_PATH], dry_run)

    typer.secho("\nСледующие шаги:", bold=True)
    typer.echo("  1. Подтверди место модуля в MODULES (порядок зависимостей SYS-01) в app/modules/registry.py")
    typer.echo(f"  2. make scaffold-entity module={name} name=<Entity>")
    typer.echo(f'  3. make makemigration module={name} name="init"  &&  make migrate')
    typer.echo("  4. make check\n")


@app.command()
def add_entity(
    name: str = typer.Argument(..., help="Имя сущности в PascalCase, напр. Order или OrderItem."),
    module: str = typer.Option(..., "--module", "-m", help="Модуль-владелец (создан `add-module`)."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Только показать, что будет сделано."),
) -> None:
    """Сгенерировать REST-сущность модуля (model/schema/dao/service/controller/test) и подключить роутер."""
    _require_module(module)
    pascal, snake, kebab = to_pascal(name), to_snake(name), to_kebab(name)
    tokens = {**_module_tokens(module), "PASCAL": pascal, "SNAKE": snake, "KEBAB": kebab}
    base = f"app/modules/{module}"
    typer.secho(f"\nREST-сущность: {module}.{pascal} (route /api/v1/{tokens['MODULE_KEBAB']}/{kebab}s)\n", bold=True)

    files = {
        f"{base}/models/{snake}.py": templates.ENTITY_MODEL,
        f"{base}/schemas/{snake}_schema.py": templates.ENTITY_SCHEMA,
        f"{base}/dao/{snake}_dao.py": templates.ENTITY_DAO,
        f"{base}/services/{snake}_service.py": templates.ENTITY_SERVICE,
        f"{base}/api/{snake}_controller.py": templates.ENTITY_CONTROLLER,
        f"tests/modules/{module}/services/__init__.py": templates.render(
            templates.MODULE_LAYER_INIT, LAYER="services (тесты)"
        ),
        f"tests/modules/{module}/services/test_{snake}_service.py": templates.ENTITY_TEST,
    }
    for rel_path, template in files.items():
        _create_file(rel_path, templates.render(template, **tokens), dry_run)

    _append_file(
        f"{base}/models/__init__.py",
        templates.render(templates.ENTITY_MODEL_IMPORT, **tokens),
        marker=f"models.{snake} import",
        dry_run=dry_run,
    )
    _append_file(
        f"{base}/permissions.py",
        templates.render(templates.ENTITY_PERMISSIONS, **tokens),
        marker=f"class {pascal}Permissions",
        dry_run=dry_run,
    )
    _append_file(
        f"{base}/api/router.py",
        templates.render(templates.ENTITY_ROUTER_INCLUDE, **tokens),
        marker=f"{snake}_router",
        dry_run=dry_run,
    )

    _format(
        [*files, f"{base}/models/__init__.py", f"{base}/permissions.py", f"{base}/api/router.py"],
        dry_run,
    )

    typer.secho("\nСледующие шаги:", bold=True)
    typer.echo(f"  1. Допиши поля модели в {base}/models/{snake}.py")
    typer.echo(f'  2. make makemigration module={module} name="add_{snake}"  &&  make migrate')
    typer.echo(f"  3. Уточни права в {base}/permissions.py (SYS-06)")
    typer.echo("  4. make check\n")


@app.command()
def add_subscriber(
    topic: str = typer.Argument(..., help="Имя enum-члена топика, напр. USER_DELETED."),
    value: str = typer.Argument(..., help="Топик: flt.<module>.<event>.v<N> или flt.<module>.jobs.<job>.v<N>."),
    module: str = typer.Option(..., "--module", "-m", help="Модуль-потребитель (создан `add-module`)."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Только показать, что будет сделано."),
) -> None:
    """Сгенерировать Kafka-консьюмер модуля: схему, сервис, член enum и хендлер на роутере модуля."""
    _require_module(module)
    if not is_valid_topic(value):
        typer.secho(
            f"  ! топик {value!r} не по формату flt.<module>.<event>.v<N> | flt.<module>.jobs.<job>.v<N> (SYS-04)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    const, snake, pascal = to_const(topic), to_snake(topic), to_pascal(topic)
    owner = value.split(".")[1]
    kind = "job" if ".jobs." in value else "event"
    if owner != module:
        _require_module(owner)
        if kind == "job":
            typer.secho(
                f"  ! команды заданий {value} принимает только модуль {owner} (SYS-04-R21)", fg=typer.colors.RED
            )
            raise typer.Exit(code=1)
    tokens = {
        **_module_tokens(module),
        "PASCAL": pascal,
        "SNAKE": snake,
        "CONST": const,
        "VALUE": value,
        "OWNER": owner,
        "KIND": kind,
        "VISIBILITY": "internal" if owner == module else "public",
    }
    base = f"app/modules/{module}"
    typer.secho(f'\nKafka subscriber: {module}.{const} = "{value}"\n', bold=True)

    files = {
        f"{base}/brokers/__init__.py": templates.BROKERS_INIT,
        f"{base}/brokers/router.py": templates.BROKERS_ROUTER,
        f"{base}/brokers/subscribers.py": templates.BROKERS_SUBSCRIBERS,
        f"{base}/brokers/messages/__init__.py": templates.BROKERS_MESSAGES_INIT,
        f"{base}/brokers/messages/{snake}_message.py": templates.SUBSCRIBER_SCHEMA,
        f"{base}/brokers/services/__init__.py": templates.BROKERS_SERVICES_INIT,
        f"{base}/brokers/services/{snake}_service.py": templates.SUBSCRIBER_SERVICE,
    }
    for rel_path, template in files.items():
        _create_file(rel_path, templates.render(template, **tokens), dry_run)

    # Декларация топика — в public/topics.py модуля-владельца (SYS-04-R21).
    owner_topics = f"app/modules/{owner}/public/topics.py"
    _create_file(owner_topics, templates.render(templates.MODULE_PUBLIC_TOPICS, **_module_tokens(owner)), dry_run)
    _append_file(
        owner_topics,
        templates.render(templates.TOPIC_DECLARATION, **tokens),
        marker=f"{const} = TopicDeclaration",
        dry_run=dry_run,
    )
    _insert_after(
        f"{base}/brokers/subscribers.py",
        anchor=f"from app.modules.{module}.brokers.router import kafka_router",
        snippet=templates.render(templates.SUBSCRIBER_HANDLER_IMPORTS, **tokens),
        marker=f"messages.{snake}_message import",
        dry_run=dry_run,
    )
    _append_file(
        f"{base}/brokers/subscribers.py",
        templates.render(templates.SUBSCRIBER_HANDLER, **tokens),
        marker=f"def handle_{snake}(",
        dry_run=dry_run,
    )
    _insert_after(
        f"{base}/module.py",
        anchor="from app.core.modules import ModuleDefinition",
        snippet=templates.render(templates.MODULE_KAFKA_IMPORTS, **tokens),
        marker="brokers.router import kafka_router",
        dry_run=dry_run,
    )
    _insert_after(
        f"{base}/module.py",
        anchor="router=router,",
        snippet="    kafka_router=kafka_router,\n",
        marker="kafka_router=kafka_router",
        dry_run=dry_run,
    )

    _format([*files, f"{base}/module.py", owner_topics], dry_run)

    typer.secho("\nСледующие шаги:", bold=True)
    typer.echo(f"  1. Реализуй обработку в {base}/brokers/services/{snake}_service.py (данные — через services/)")
    typer.echo(f"  2. Уточни payload в {base}/brokers/messages/{snake}_message.py")
    typer.echo(f"  3. Добавь тест в tests/modules/{module}/brokers/ (TestKafkaBroker)")
    typer.echo("  4. make check\n")


@app.command()
def list_modules() -> None:
    """Напечатать модули реестра построчно (используют `make migrate` и CI)."""
    for name in read_registry():
        typer.echo(name)


if __name__ == "__main__":
    app()
