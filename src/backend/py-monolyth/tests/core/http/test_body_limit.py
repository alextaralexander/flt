"""Ограничение размера тела запроса: больше `HTTP_MAX_JSON_BODY_BYTES` — `413 core.payload_too_large` (SYS-03-R26)."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from configs.settings import settings
from tests.core.http.conftest import make_client


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-03-R26")]

LIMIT = 64


@pytest.fixture
def limited_app(http_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Приложение с маленьким лимитом тела и эхо-роутом."""
    monkeypatch.setattr(settings, "HTTP_MAX_JSON_BODY_BYTES", LIMIT)

    @http_app.post("/api/v1/core-test/echo")
    async def echo(payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    return http_app


async def _post(app: FastAPI, content: bytes, headers: dict[str, str] | None = None) -> Any:
    async with make_client(app) as client:
        return await client.post(
            "/api/v1/core-test/echo", content=content, headers={"Content-Type": "application/json", **(headers or {})}
        )


async def test_body_within_limit_passes(limited_app: FastAPI) -> None:
    """Тело не больше лимита обрабатывается как обычно."""
    response = await _post(limited_app, b'{"a": "x"}')
    assert response.status_code == 200
    assert response.json() == {"a": "x"}


async def test_content_length_over_limit_is_rejected(limited_app: FastAPI) -> None:
    """`Content-Length` больше лимита — 413 в конверте ошибок, обработчик не вызывается."""
    response = await _post(limited_app, b'{"a": "' + b"x" * LIMIT + b'"}')
    assert response.status_code == 413
    assert response.json()["messages"]["ERROR"][0]["code"] == "core.payload_too_large"


async def test_streamed_body_over_limit_is_rejected(limited_app: FastAPI) -> None:
    """Тело без `Content-Length` (chunked) считается по мере чтения и тоже обрывается 413."""

    async def chunks() -> Any:
        for _ in range(4):
            yield b"x" * LIMIT

    async with make_client(limited_app) as client:
        response = await client.post(
            "/api/v1/core-test/echo", content=chunks(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 413
    assert response.json()["messages"]["ERROR"][0]["code"] == "core.payload_too_large"


def test_default_limit_is_one_mebibyte() -> None:
    """Значение по умолчанию — 1 МиБ."""
    assert type(settings).model_fields["HTTP_MAX_JSON_BODY_BYTES"].default == 1024 * 1024


async def test_client_fixture_unaffected(http_client: AsyncClient) -> None:
    """Служебные эндпоинты без тела не затрагиваются ограничением."""
    response = await http_client.get("/v1/health")
    assert response.status_code == 200
