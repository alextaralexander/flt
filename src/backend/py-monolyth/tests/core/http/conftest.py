"""Fixture тестов HTTP-слоя shared kernel.

`http_app` — свежий экземпляр `create_app()` (те же middleware и обработчики исключений, что
в продовом приложении) для регистрации тестовых роутов; `http_client` — ASGI-клиент к нему.
"""

from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.support.redis_instances import redis_instances  # noqa: F401


@pytest.fixture
def http_app() -> FastAPI:
    """Новый экземпляр приложения для тестовых роутов."""
    return create_app()


def make_client(app: FastAPI, **kwargs: object) -> AsyncClient:
    """ASGI-клиент к приложению (без исключений сервера наружу — как у реального клиента)."""
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        **kwargs,  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def http_client(http_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """ASGI-клиент к `http_app`."""
    async with make_client(http_app) as client:
        yield client


@pytest.fixture
def client_factory() -> Callable[..., AsyncClient]:
    """Фабрика ASGI-клиентов к произвольному приложению (несколько «инстансов»)."""
    return make_client
