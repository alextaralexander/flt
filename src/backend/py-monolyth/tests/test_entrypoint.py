"""Тесты точки входа `python -m app`: выбор процесса по `APP_ROLE` (ADR-004, раздел 3.5)."""

from typing import Any

import pytest
from fastapi import FastAPI
from faststream.asgi import AsgiFastStream

import app.__main__ as entrypoint
from configs.settings import AppRole, settings


pytestmark = pytest.mark.no_db


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    """Подменяет `uvicorn.run`: тест получает приложение и параметры запуска без открытия сокета."""
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(entrypoint.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    return calls


def _use_role(monkeypatch: pytest.MonkeyPatch, role: AppRole) -> None:
    """Задаёт роль процесса в настройках на время теста."""
    monkeypatch.setattr(settings, "APP_ROLE", role)


class TestRoles:
    """Каждая роль запускает свой процесс (Arrange / Act / Assert)."""

    def test_api_runs_http_app_behind_proxy(
        self, monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[tuple[Any, dict[str, Any]]]
    ) -> None:
        """Роль `api`: FastAPI без брокера, uvicorn с proxy_headers и FORWARDED_ALLOW_IPS (ADR-012)."""
        # - Arrange -
        _use_role(monkeypatch, AppRole.API)

        # - Act -
        code = entrypoint.main([])

        # - Assert -
        [(application, kwargs)] = uvicorn_calls
        assert code == 0
        assert isinstance(application, FastAPI)
        assert getattr(application.state, "worker", None) is None
        assert kwargs["port"] == settings.FAST_API_PORT
        assert kwargs["proxy_headers"] is True
        assert kwargs["forwarded_allow_ips"] == settings.FORWARDED_ALLOW_IPS
        assert kwargs["timeout_graceful_shutdown"] == settings.SHUTDOWN_GRACE_SECONDS
        assert application.openapi_url == "/api/openapi.json"
        assert application.docs_url == "/api/docs"

    def test_all_runs_http_app_with_worker(
        self, monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[tuple[Any, dict[str, Any]]]
    ) -> None:
        """Роль `all`: тот же HTTP-процесс, но с брокером воркера в lifespan."""
        # - Arrange -
        _use_role(monkeypatch, AppRole.ALL)

        # - Act -
        entrypoint.main([])

        # - Assert -
        [(application, _)] = uvicorn_calls
        assert isinstance(application.state.worker, AsgiFastStream)

    def test_worker_runs_faststream_on_service_port(
        self, monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[tuple[Any, dict[str, Any]]]
    ) -> None:
        """Роль `worker`: AsgiFastStream на служебном порту `WORKER_HTTP_PORT`."""
        # - Arrange -
        _use_role(monkeypatch, AppRole.WORKER)

        # - Act -
        entrypoint.main([])

        # - Assert -
        [(application, kwargs)] = uvicorn_calls
        assert isinstance(application, AsgiFastStream)
        assert kwargs["port"] == settings.WORKER_HTTP_PORT == 8001

    def test_migrate_upgrades_every_registry_module(
        self, monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[tuple[Any, dict[str, Any]]]
    ) -> None:
        """Роль `migrate`: `upgrade head` по секции каждого модуля реестра, HTTP не поднимается."""
        # - Arrange -
        upgraded: list[tuple[str, str]] = []
        monkeypatch.setattr(
            entrypoint.command,
            "upgrade",
            lambda config, revision: upgraded.append((config.config_ini_section, revision)),
        )

        # - Act -
        entrypoint.run_migrations(["first_mod", "second_mod"])
        _use_role(monkeypatch, AppRole.MIGRATE)
        code = entrypoint.main([])

        # - Assert -
        assert upgraded[:2] == [("first_mod", "head"), ("second_mod", "head")]
        assert code == 0
        assert uvicorn_calls == []

    def test_media_agent_is_not_available_yet(
        self, monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[tuple[Any, dict[str, Any]]]
    ) -> None:
        """Роль `media_agent` (этап 6) завершается с понятной ошибкой, ничего не запуская."""
        # - Arrange -
        _use_role(monkeypatch, AppRole.MEDIA_AGENT)

        # - Act -
        code = entrypoint.main([])

        # - Assert -
        assert code == 2
        assert uvicorn_calls == []

    def test_unknown_arguments_are_rejected(self) -> None:
        """Неизвестный аргумент — код 2."""
        # - Act / Assert -
        assert entrypoint.main(["unexpected"]) == 2


class TestHealthcheck:
    """`python -m app healthcheck` проверяет `/v1/health` на порту роли."""

    def test_migrate_has_nothing_to_check(self) -> None:
        """У роли migrate нет HTTP — проверка успешна."""
        # - Act / Assert -
        assert entrypoint.healthcheck(AppRole.MIGRATE) == 0

    def test_unreachable_port_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Нет процесса на порту роли — код 1."""
        # - Arrange -
        monkeypatch.setattr(settings, "WORKER_HTTP_PORT", 1)
        _use_role(monkeypatch, AppRole.WORKER)

        # - Act / Assert -
        assert entrypoint.main(["healthcheck"]) == 1

    def test_healthy_port_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ответ 200 — код 0."""

        # - Arrange -
        class Response:
            """Ответ-заглушка `urlopen`."""

            status = 200

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        requested: list[str] = []
        monkeypatch.setattr(
            entrypoint.urllib.request, "urlopen", lambda url, timeout: requested.append(url) or Response()
        )

        # - Act -
        code = entrypoint.healthcheck(AppRole.API)

        # - Assert -
        assert code == 0
        assert requested == [f"http://127.0.0.1:{settings.FAST_API_PORT}/v1/health"]
