"""Тесты `X-Request-ID` и `RequestContext` (SYS-03-R20)."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.http.context import RequestContext, RequestContextDep


pytestmark = pytest.mark.no_db


@pytest.fixture
def context_app(http_app: FastAPI) -> FastAPI:
    """Приложение с роутом, возвращающим контекст запроса."""

    @http_app.get("/api/v1/core-test/context")
    async def context(ctx: RequestContextDep) -> dict[str, str | None]:
        return {"request_id": ctx.request_id, "instance_id": ctx.instance_id, "locale": ctx.locale}

    return http_app


@pytest.mark.req("SYS-03-R20")
async def test_incoming_request_id_is_returned(context_app: FastAPI, http_client: AsyncClient) -> None:
    """ID запроса от HAProxy возвращается в ответе и доступен через `RequestContext`."""
    # - Act -
    response = await http_client.get("/api/v1/core-test/context", headers={"X-Request-ID": "haproxy-req-42"})

    # - Assert -
    assert response.headers["X-Request-ID"] == "haproxy-req-42"
    assert response.json()["request_id"] == "haproxy-req-42"


@pytest.mark.req("SYS-03-R20")
@pytest.mark.parametrize("header", [None, "", "bad id with spaces", "x" * 200])
async def test_missing_or_invalid_request_id_generated(
    context_app: FastAPI, http_client: AsyncClient, header: str | None
) -> None:
    """Без заголовка (или с недопустимым значением) генерируется UUID."""
    headers = {"X-Request-ID": header} if header is not None else {}
    response = await http_client.get("/api/v1/core-test/context", headers=headers)
    generated = response.headers["X-Request-ID"]
    assert str(uuid.UUID(generated)) == generated
    assert response.json()["request_id"] == generated


@pytest.mark.req("SYS-03-R20")
async def test_request_id_in_error_envelope(context_app: FastAPI, http_client: AsyncClient) -> None:
    """`request_id` конверта 404 совпадает с заголовком ответа."""
    response = await http_client.get("/api/v1/core-test/none", headers={"X-Request-ID": "req-404"})
    assert response.status_code == 404
    assert response.json()["request_id"] == "req-404" == response.headers["X-Request-ID"]


@pytest.mark.req("SYS-03-R20")
async def test_context_instance_id_is_hostname(
    context_app: FastAPI, http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`RequestContext.instance_id` — `HOSTNAME` инстанса (тот же, что в `X-Instance-Id`, SYS-05-R5)."""
    # - Arrange -
    monkeypatch.setenv("HOSTNAME", "flt-api-2")

    # - Act -
    response = await http_client.get("/api/v1/core-test/context")

    # - Assert -
    assert response.json()["instance_id"] == "flt-api-2"


@pytest.mark.req("SYS-03-R20")
def test_request_context_is_immutable() -> None:
    """`RequestContext` — неизменяемое значение одного запроса."""
    ctx = RequestContext(request_id="r", instance_id="i", locale="ru", user=None)
    with pytest.raises(AttributeError):
        ctx.locale = "en"  # type: ignore[misc]
