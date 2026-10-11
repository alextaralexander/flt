"""Тесты параметров engine по роли запуска (ADR-003, раздел 2.2 и правило 2; SYS-05)."""

import pytest

from app.core.dao.db_helpers.db_connection import engine_options
from configs.settings import AppRole


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-05-R40")]


@pytest.mark.parametrize(
    ("role", "pool_size", "max_overflow", "statement_timeout"),
    [
        (AppRole.API, 10, 10, "30s"),
        (AppRole.ALL, 10, 10, "30s"),
        (AppRole.WORKER, 5, 5, "10min"),
        (AppRole.MEDIA_AGENT, 5, 5, "10min"),
        (AppRole.MIGRATE, 1, 0, "10min"),
    ],
)
def test_pool_size_by_role(role: AppRole, pool_size: int, max_overflow: int, statement_timeout: str) -> None:
    """Размер пула и statement_timeout зависят от роли; общие параметры одинаковы."""
    # - Act -
    options = engine_options(role)

    # - Assert -
    server_settings = options["connect_args"]["server_settings"]
    assert (options["pool_size"], options["max_overflow"]) == (pool_size, max_overflow)
    assert (options["pool_pre_ping"], options["pool_recycle"], options["pool_timeout"]) == (True, 1800, 10)
    assert server_settings["statement_timeout"] == statement_timeout
    assert server_settings["search_path"] == "public"
    assert server_settings["timezone"] == "UTC"
    assert server_settings["idle_in_transaction_session_timeout"] == "60s"


def test_application_name_identifies_role_and_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """`application_name` = `flt-<role>-<instance_id>`, не длиннее 63 символов."""
    # - Arrange -
    monkeypatch.setenv("HOSTNAME", "api-" + "x" * 80)

    # - Act -
    name = engine_options(AppRole.API)["connect_args"]["server_settings"]["application_name"]

    # - Assert -
    assert name.startswith("flt-api-api-")
    assert len(name) == 63
