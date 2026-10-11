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

    def run_api_server(server: entrypoint.ApiServer) -> None:
        """Роли `api` и `all` запускаются через `ApiServer` (закрытие `/ws` с причиной при остановке)."""
        config = server.config
        calls.append(
            (
                config.app,
                {
                    "port": config.port,
                    "proxy_headers": config.proxy_headers,
                    "forwarded_allow_ips": config.forwarded_allow_ips,
                    "timeout_graceful_shutdown": config.timeout_graceful_shutdown,
                },
            )
        )

    monkeypatch.setattr(entrypoint.ApiServer, "run", run_api_server)
    return calls


def _use_role(monkeypatch: pytest.MonkeyPatch, role: AppRole) -> None:
    """Задаёт роль процесса в настройках на время теста."""
    monkeypatch.setattr(settings, "APP_ROLE", role)


class _RecordingHub:
    """Хаб-проба: записывает момент остановки."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def stop(self) -> None:
        self.events.append("hub.stop")


@pytest.mark.req("SYS-04-R18")
async def test_api_server_closes_websockets_before_uvicorn_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """При остановке `ApiServer` сначала закрывает `/ws` с причиной `instance_shutdown`, затем uvicorn — свои."""
    # - Arrange -
    events: list[str] = []

    async def uvicorn_shutdown(self: Any, sockets: Any = None) -> None:
        events.append("uvicorn.shutdown")

    monkeypatch.setattr(entrypoint.uvicorn.Server, "shutdown", uvicorn_shutdown)
    server = entrypoint.ApiServer(entrypoint.uvicorn.Config(FastAPI()), _RecordingHub(events))  # type: ignore[arg-type]

    # - Act -
    await server.shutdown()

    # - Assert -
    assert events == ["hub.stop", "uvicorn.shutdown"]


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

    @pytest.mark.req("SYS-04-R23")
    def test_migrate_applies_module_topics(
        self, monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[tuple[Any, dict[str, Any]]]
    ) -> None:
        """Роль `migrate` после миграций создаёт топики по декларациям модулей реестра."""
        # - Arrange -
        applied: list[list[Any]] = []

        async def fake_apply(declarations: Any) -> list[str]:
            applied.append(list(declarations))
            return []

        monkeypatch.setattr(entrypoint.command, "upgrade", lambda config, revision: None)
        monkeypatch.setattr(entrypoint, "apply_topics", fake_apply)
        _use_role(monkeypatch, AppRole.MIGRATE)

        # - Act -
        code = entrypoint.main([])

        # - Assert -
        assert code == 0
        assert applied == [[]]

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


@pytest.mark.req("SYS-04-R28")
class TestDlqCommands:
    """`python -m app dlq list|replay` — разбор DLQ вручную."""

    def test_list_and_replay(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """Аргументы командной строки передаются в функции DLQ, результат печатается."""
        # - Arrange -
        calls: list[tuple[str, dict[str, Any]]] = []

        async def fake_list(topic: str, **kwargs: Any) -> list[dict[str, Any]]:
            calls.append(("list", {"topic": topic, **kwargs}))
            return [{"event_id": "e1"}]

        async def fake_replay(topic: str, **kwargs: Any) -> list[str]:
            calls.append(("replay", {"topic": topic, **kwargs}))
            return ["e1"]

        monkeypatch.setattr(entrypoint, "list_dlq", fake_list)
        monkeypatch.setattr(entrypoint, "replay_dlq", fake_replay)

        # - Act -
        listed = entrypoint.main(["dlq", "list", "--topic", "flt.m.x.v1"])
        replayed = entrypoint.main(
            ["dlq", "replay", "--topic", "flt.m.x.v1", "--event-id", "e1", "--dry-run", "--consumer", "m.h"]
        )

        # - Assert -
        assert (listed, replayed) == (0, 0)
        assert calls == [
            ("list", {"topic": "flt.m.x.v1", "since": None}),
            (
                "replay",
                {"topic": "flt.m.x.v1", "event_ids": ["e1"], "consumer": "m.h", "dry_run": True, "force": False},
            ),
        ]
        assert "e1" in capsys.readouterr().out

    def test_replay_limit_returns_error_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Превышение лимита повторов без `--force` — код возврата 1."""

        async def limited(topic: str, **kwargs: Any) -> list[str]:
            raise entrypoint.DlqReplayLimitError("limit")

        monkeypatch.setattr(entrypoint, "replay_dlq", limited)
        assert entrypoint.main(["dlq", "replay", "--topic", "flt.m.x.v1"]) == 1
