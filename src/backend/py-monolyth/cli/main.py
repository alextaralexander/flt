"""Typer-скаффолдер: генерация REST-сущностей и Kafka-сабскрайберов по образцу проекта.

Примеры::

    python -m cli add-entity Order
    python -m cli add-subscriber ORDER_CREATED "svc.order.created.01"
    python -m cli add-entity Order --dry-run
    python -m cli issue-token 00000000-0000-0000-0000-000000000002 --role ADMIN

Скаффолдер не перезаписывает существующие файлы и идемпотентен по вставкам
(повторный запуск не дублирует импорты/строки роутера/enum-члены).
"""

# Вызываем только ruff с фиксированными аргументами, без shell.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Annotated

import typer

from cli import templates
from cli.naming import to_const, to_pascal, to_snake


ROOT = Path(__file__).resolve().parent.parent

app = typer.Typer(
    add_completion=False,
    help="Скаффолдер шаблона: REST-сущности, брокер-консьюмеры, выпуск dev-JWT.",
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
    """Вставить snippet сразу после строки, содержащей anchor (если marker отсутствует)."""
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
    typer.secho(
        f"  ! якорь не найден в {rel_path}: '{anchor}' — впиши вручную",
        fg=typer.colors.RED,
    )


def _format(rel_paths: list[str], dry_run: bool) -> None:
    """Привести затронутые файлы к стилю проекта (ruff: сортировка импортов + формат).

    Делает вывод скаффолдера длинно-/коротко-имённо устойчивым: ruff сам решает,
    обернуть импорт в скобки или оставить в строку, по `line-length` из pyproject.
    """
    if dry_run:
        return
    existing = [str(ROOT / p) for p in rel_paths if (ROOT / p).exists()]
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


# --- Команды ----------------------------------------------------------------


@app.command()
def add_entity(
    name: str = typer.Argument(..., help="Имя сущности в PascalCase, напр. Order или OrderItem."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Только показать, что будет сделано."),
) -> None:
    """Сгенерировать REST-сущность (schema/dao/service/controller/test) и подключить роутер."""
    pascal, snake, upper = to_pascal(name), to_snake(name), to_const(name)
    typer.secho(f"\nREST-сущность: {pascal} (route /{snake})\n", bold=True)

    tokens = {"PASCAL": pascal, "SNAKE": snake, "UPPER": upper}
    _create_file(f"app/api/schemas/{snake}_schema.py", templates.render(templates.ENTITY_SCHEMA, **tokens), dry_run)
    _create_file(f"app/api/dao/{snake}_dao.py", templates.render(templates.ENTITY_DAO, **tokens), dry_run)
    _create_file(f"app/api/services/{snake}_service.py", templates.render(templates.ENTITY_SERVICE, **tokens), dry_run)
    _create_file(
        f"app/api/controllers/{snake}_controller.py",
        templates.render(templates.ENTITY_CONTROLLER, **tokens),
        dry_run,
    )
    _create_file(
        f"tests/api/services/test_{snake}_service.py",
        templates.render(templates.ENTITY_TEST, **tokens),
        dry_run,
    )

    _append_file(
        "app/core/security/permissions.py",
        templates.render(templates.ENTITY_PERMISSIONS, **tokens),
        marker=f"class {pascal}Permissions",
        dry_run=dry_run,
    )

    router_snippet = (
        f"from app.api.controllers.{snake}_controller import router as {snake}_router  # noqa: E402\n\n"
        f"v1_router.include_router({snake}_router)\n"
    )
    _append_file(
        "app/api/controllers/__init__.py",
        router_snippet,
        marker=f"{snake}_router",
        dry_run=dry_run,
    )

    _format(
        [
            f"app/api/schemas/{snake}_schema.py",
            f"app/api/dao/{snake}_dao.py",
            f"app/api/services/{snake}_service.py",
            f"app/api/controllers/{snake}_controller.py",
            f"tests/api/services/test_{snake}_service.py",
            "app/core/security/permissions.py",
            "app/api/controllers/__init__.py",
        ],
        dry_run,
    )

    typer.secho("\nСледующие шаги (вручную):", bold=True)
    typer.echo(f"  1. Добавь модель `{pascal}` в app/core/dao/models.py, напр.:")
    typer.echo(f"       class {pascal}(BaseEntityModel, SchemaBase):")
    typer.echo(f'           __tablename__ = "{snake}"')
    typer.echo('           name: Mapped[str] = mapped_column(String, comment="Название")')
    typer.echo(f'  2. make makemigration name="add_{snake}"  &&  make migrate')
    typer.echo("  3. Уточни значения прав в app/core/security/permissions.py")
    typer.echo("  4. make check\n")


@app.command()
def add_subscriber(
    topic: str = typer.Argument(..., help="Имя enum-члена топика, напр. ORDER_CREATED."),
    value: str = typer.Argument(..., help="Значение Kafka-топика, напр. svc.order.created.01."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Только показать, что будет сделано."),
) -> None:
    """Сгенерировать Kafka-сабскрайбер: схему, сервис, enum-член и хендлер."""
    const, snake, pascal = to_const(topic), to_snake(topic), to_pascal(topic)
    typer.secho(f'\nKafka subscriber: {const} = "{value}"\n', bold=True)

    tokens = {"PASCAL": pascal, "SNAKE": snake, "CONST": const, "VALUE": value}

    _create_file(
        f"app/brokers/kafka/schemas/subscriber_messages/{snake}_schema.py",
        templates.render(templates.SUBSCRIBER_SCHEMA, **tokens),
        dry_run,
    )
    _create_file(
        f"app/brokers/kafka/services/{snake}_service.py",
        templates.render(templates.SUBSCRIBER_SERVICE, **tokens),
        dry_run,
    )
    _insert_after(
        "app/brokers/kafka/schemas/enums.py",
        anchor='"""Kafka Subscriber Topics."""',
        snippet=f'\n    {const} = "{value}"\n',  # ведущая пустая строка после docstring (black)
        marker=f"{const} =",
        dry_run=dry_run,
    )
    _append_file(
        "app/brokers/kafka/subscribers.py",
        templates.render(templates.SUBSCRIBER_HANDLER, **tokens),
        marker=f"subscriber_to_{snake}",
        dry_run=dry_run,
    )

    _format(
        [
            f"app/brokers/kafka/schemas/subscriber_messages/{snake}_schema.py",
            f"app/brokers/kafka/services/{snake}_service.py",
            "app/brokers/kafka/schemas/enums.py",
            "app/brokers/kafka/subscribers.py",
        ],
        dry_run,
    )

    typer.secho("\nСледующие шаги (вручную):", bold=True)
    typer.echo(f"  1. Реализуй бизнес-логику в app/brokers/kafka/services/{snake}_service.py")
    typer.echo(f"  2. Уточни payload в схеме {pascal}Schema при необходимости")
    typer.echo("  3. Добавь тест в tests/brokers/kafka/ (см. test_kafka_subscribers.py)")
    typer.echo("  4. make check\n")


@app.command()
def issue_token(
    user_id: str = typer.Argument(..., help="USER_ID пользователя (UUID)."),
    permission: Annotated[
        list[str] | None,
        typer.Option("--permission", "-p", help="Прямой permission (можно повторять)."),
    ] = None,
    role: Annotated[
        list[str] | None,
        typer.Option("--role", "-r", help="Роль из JWT_ROLE_PERMISSIONS (можно повторять)."),
    ] = None,
    expires_in: int = typer.Option(3600, "--expires-in", help="Время жизни токена в секундах."),
) -> None:
    """Выпустить JWT, подписанный JWT_SECRET_KEY текущего стенда (для локальной разработки)."""
    # Импорт внутри команды: скаффолдинг не должен требовать настроек стенда.
    from app.core.security.auth_service import get_auth_service

    token = get_auth_service().create_token(
        user_id=user_id,
        permissions=permission or [],
        roles=role or [],
        expires_in_seconds=expires_in,
    )
    typer.echo(token)


if __name__ == "__main__":
    app()
