"""Smoke-тесты жизненного цикла приложения: ресурсы создаются и освобождаются, в роли `all` — и брокер."""

import pytest

from app.main import create_app, lifespan
from configs.settings import AppRole


pytestmark = pytest.mark.no_db


async def test_lifespan_creates_and_releases_resources() -> None:
    """Роль `api`: на старте ресурсы попадают в app.state, брокера нет, остановка без ошибок."""
    # - Arrange -
    application = create_app([], role=AppRole.API)

    # - Act -
    async with lifespan(application):
        # - Assert (startup) -
        assert application.state.db_engine is not None
        assert application.state.tracer_provider is not None
        assert getattr(application.state, "worker", None) is None


async def test_lifespan_of_role_all_runs_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Роль `all`: lifespan HTTP-приложения поднимает брокер воркера и останавливает его на выходе."""
    # - Arrange -
    application = create_app([], role=AppRole.ALL)
    broker = application.state.worker.brokers[0]
    calls: list[str] = []

    async def fake_start() -> None:
        calls.append("start")

    async def fake_stop(*args: object, **kwargs: object) -> None:
        calls.append("stop")

    monkeypatch.setattr(broker, "start", fake_start)
    monkeypatch.setattr(broker, "stop", fake_stop)

    # - Act -
    async with lifespan(application):
        # - Assert (startup) -
        assert calls == ["start"]

    # - Assert (shutdown) -
    assert calls == ["start", "stop"]
