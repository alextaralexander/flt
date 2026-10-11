"""Тесты заголовка `X-Instance-Id` в ответах инстанса (SYS-05-R5)."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from starlette.types import Message, Receive, Scope, Send

from app.core.http.instance_header import INSTANCE_HEADER, InstanceIdMiddleware
from configs.stands import instance_id
from tests.conftest import mocked_function


pytestmark = pytest.mark.req("SYS-05-R5")


class TestInstanceHeaderInApp:
    """Ответы приложения роли `api` несут `X-Instance-Id` = `HOSTNAME` инстанса."""

    @pytest.mark.parametrize(
        ("method", "path", "status"),
        [
            ("GET", "/v1/health", 200),
            ("GET", "/api/v1/unknown-route", 404),
            ("POST", "/mocked_body", 422),
        ],
    )
    async def test_header_on_success_and_errors(self, client: AsyncClient, method: str, path: str, status: int) -> None:
        """Успешные ответы и ошибки в конверте `ErrorResponseV1` содержат заголовок."""
        # - Act -
        response = await client.request(method, path, json={})

        # - Assert -
        assert response.status_code == status
        assert response.headers[INSTANCE_HEADER] == instance_id()

    async def test_header_on_unhandled_error(self, client: AsyncClient, overridden_app: FastAPI) -> None:
        """Ответ 500 на неперехваченное исключение тоже несёт заголовок."""

        # - Arrange -
        async def raise_error() -> None:
            raise RuntimeError("boom")

        overridden_app.dependency_overrides[mocked_function] = raise_error

        # - Act -
        response = await client.get("/mocked_endpoint")

        # - Assert -
        assert response.status_code == 500
        assert response.headers[INSTANCE_HEADER] == instance_id()


class TestInstanceIdMiddleware:
    """ASGI-уровень: HTTP, handshake WebSocket и прочие события."""

    @pytest.mark.no_db
    @pytest.mark.parametrize(
        ("scope_type", "start_type"),
        [
            ("http", "http.response.start"),
            ("websocket", "websocket.accept"),
            ("websocket", "websocket.http.response.start"),
        ],
    )
    async def test_header_added_to_response_start(self, scope_type: str, start_type: str) -> None:
        """Заголовок дописывается к началу ответа HTTP и handshake WebSocket, прочие сообщения не меняются."""
        # - Arrange -
        sent: list[Message] = []

        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": start_type, "headers": [(b"x-other", b"1")]})
            await send({"type": "http.response.body", "body": b""})

        async def send(message: Message) -> None:
            sent.append(message)

        async def receive() -> Message:
            return {"type": "http.request"}

        middleware = InstanceIdMiddleware(inner, instance="flt-api-2")

        # - Act -
        await middleware({"type": scope_type}, receive, send)

        # - Assert -
        assert sent[0]["headers"] == [(b"x-other", b"1"), (b"x-instance-id", b"flt-api-2")]
        assert "headers" not in sent[1]

    @pytest.mark.no_db
    async def test_lifespan_passes_through(self) -> None:
        """События lifespan проходят без изменений."""
        # - Arrange -
        sent: list[Message] = []

        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "lifespan.startup.complete"})

        async def send(message: Message) -> None:
            sent.append(message)

        async def receive() -> Message:
            return {"type": "lifespan.startup"}

        # - Act -
        await InstanceIdMiddleware(inner, instance="flt-api-1")({"type": "lifespan"}, receive, send)

        # - Assert -
        assert sent == [{"type": "lifespan.startup.complete"}]
