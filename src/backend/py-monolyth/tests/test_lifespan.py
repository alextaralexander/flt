"""Smoke-тест жизненного цикла приложения: ресурсы создаются и освобождаются."""

import pytest

from app.main import app, lifespan


pytestmark = pytest.mark.no_db


async def test_lifespan_creates_and_releases_resources() -> None:
    """На старте ресурсы попадают в app.state, на остановке освобождаются без ошибок."""
    # - Act -
    async with lifespan(app):
        # - Assert (startup) -
        assert app.state.db_engine is not None
        assert app.state.tracer_provider is not None
