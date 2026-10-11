"""Миграции — отдельный шаг роли `migrate`; роли `api` и `worker` не выполняют DDL при старте (SYS-05-R33).

ADR-003 (п. 2.5), ADR-004 (роль `migrate`); настройки `MIGRATE_ON_START` в проекте нет.
"""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import MetaData

import app.__main__ as entrypoint
from app.main import create_app
from configs.settings import AppRole, settings
from tests.architecture import checks


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-05-R33")]


@pytest.fixture
def ddl_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Перехватывает `alembic.command.upgrade` и `MetaData.create_all`; процессы ролей не запускаются."""
    calls: list[str] = []
    monkeypatch.setattr(command, "upgrade", lambda *args, **kwargs: calls.append("alembic upgrade"))
    monkeypatch.setattr(MetaData, "create_all", lambda *args, **kwargs: calls.append("create_all"))
    monkeypatch.setattr(entrypoint.uvicorn, "run", lambda *args, **kwargs: calls.append("serve"))
    monkeypatch.setattr(entrypoint.ApiServer, "run", lambda *args, **kwargs: calls.append("serve"))
    return calls


class TestNoRuntimeDdl:
    """В runtime-коде нет `alembic.command` (кроме точки входа роли `migrate`), `create_all` и DDL-строк."""

    def test_current_tree(self) -> None:
        """Текущее дерево."""
        assert checks.runtime_ddl_violations(checks.SERVICE_ROOT) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Сгенерированные скаффолдером модули (их ревизии Alembic — вне runtime)."""
        assert checks.runtime_ddl_violations(sample_tree) == []

    def test_violations_are_reported(self, tmp_path: Path) -> None:
        """Импорт `alembic.command`/`op`, `create_all` и строка DDL обнаруживаются; докстринг — нет."""
        # - Arrange -
        path = tmp_path / "app" / "modules" / "rogue" / "services" / "bootstrap.py"
        path.parent.mkdir(parents=True)
        path.write_text(
            '"""Создаёт таблицы при старте: CREATE TABLE в докстринге не считается."""\n\n'
            "from alembic import command, op\n\n\n"
            "async def on_startup(engine, metadata):\n"
            "    await engine.run_sync(metadata.create_all)\n"
            "    metadata.create_all(engine)\n"
            "    await engine.execute('alter table rogue.items add column x int')\n",
            encoding="utf-8",
        )

        # - Act -
        violations = checks.runtime_ddl_violations(tmp_path)

        # - Assert -
        rel = "app/modules/rogue/services/bootstrap.py"
        assert violations == [
            f"{rel}:3: импорт alembic.command",
            f"{rel}:3: импорт alembic.op",
            f"{rel}:8: вызов .create_all()",
            f"{rel}:9: DDL в строке 'alter table rogue.items add column x int'",
        ]


def test_no_migrate_on_start_setting() -> None:
    """`MIGRATE_ON_START` нет в коде, configs, envs, Makefile, Dockerfile и `.env.template` сервиса."""
    assert checks.migrate_on_start_violations(checks.SERVICE_ROOT) == []


@pytest.mark.parametrize("role", [AppRole.API, AppRole.WORKER, AppRole.ALL])
def test_serving_roles_do_not_migrate(monkeypatch: pytest.MonkeyPatch, ddl_calls: list[str], role: AppRole) -> None:
    """`python -m app` ролей `api`, `worker`, `all` запускает сервер без миграций и `create_all`."""
    # - Arrange -
    monkeypatch.setattr(settings, "APP_ROLE", role)

    # - Act -
    exit_code = entrypoint.main([])

    # - Assert -
    assert exit_code == 0
    assert ddl_calls == ["serve"]


async def test_api_lifespan_runs_no_ddl(ddl_calls: list[str]) -> None:
    """Startup и shutdown HTTP-приложения роли `api` не вызывают миграции и `create_all`."""
    # - Arrange -
    application = create_app(modules=[], role=AppRole.API)
    state: dict[str, Any] = {}

    # - Act -
    async with application.router.lifespan_context(application):
        state["started"] = True

    # - Assert -
    assert state == {"started": True}
    assert ddl_calls == []
