"""Эндпоинт `/ws`: handshake, конверт, ping/pong, коды закрытия, лимит соединений (SYS-04-R2, R3, R10, R11, R14)."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.dao.caching import ModuleRedis
from app.core.ws.endpoint import ConnectionLimiter
from app.core.ws.protocol import WsConfig
from tests.core.ws.conftest import envelope


Bearer = Callable[..., dict[str, str]]


def _closed_with(ws: Any) -> int:
    """Код закрытия соединения сервером."""
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    return int(closed.value.code)


@pytest.mark.req("SYS-04-R2")
def test_handshake_without_token_closes_4401(ws_app: Callable[..., FastAPI]) -> None:
    """Без аутентификации соединение закрывается `4401` без сообщений."""
    # - Arrange -
    client = TestClient(ws_app())

    # - Act -
    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/ws") as ws:
        ws.receive_json()

    # - Assert -
    assert closed.value.code == 4401


@pytest.mark.req("SYS-04-R11")
def test_client_ping_gets_pong_with_increasing_seq(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """`ws.ping` клиента → `ws.pong` с тем же correlation_id; `seq` сервера растёт с 0."""
    # - Arrange -
    client = TestClient(ws_app())
    correlation_id = str(uuid4())

    # - Act -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        ws.send_text(envelope("ws.ping", {"client_ts": "t1"}, correlation_id=correlation_id))
        first = ws.receive_json()
        ws.send_text(envelope("ws.ping", seq=1))
        second = ws.receive_json()

    # - Assert -
    assert first["type"] == "ws.pong"
    assert first["correlation_id"] == correlation_id
    assert first["payload"]["client_ts"] == "t1"
    assert set(first) == {"type", "correlation_id", "channel", "seq", "ts", "payload"}
    assert (first["seq"], second["seq"]) == (0, 1)


@pytest.mark.req("SYS-04-R3")
def test_invalid_envelope_errors_and_three_in_row_close_1008(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Лишнее поле — `ws.invalid_envelope`; третье подряд — закрытие `1008`."""
    # - Arrange -
    client = TestClient(ws_app())

    # - Act / Assert -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        ws.send_text('{"type": "ws.ping", "extra": 1}')
        assert ws.receive_json()["payload"]["code"] == "ws.invalid_envelope"
        ws.send_text("not json")
        assert ws.receive_json()["payload"]["code"] == "ws.invalid_envelope"
        ws.send_text("[]")
        assert _closed_with(ws) == 1008


@pytest.mark.req("SYS-04-R10")
def test_message_too_big_closes_1009(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Сообщение больше лимита — `1009 message_too_big`."""
    # - Arrange -
    client = TestClient(ws_app(WsConfig(max_message_bytes=100)))

    # - Act / Assert -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        ws.send_text(envelope("ws.ping", {"pad": "x" * 200}))
        assert _closed_with(ws) == 1009


@pytest.mark.req("SYS-04-R4")
def test_unknown_type_gives_error(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Тип без обработчика — `ws.error` с кодом `ws.unknown_type`."""
    # - Arrange -
    client = TestClient(ws_app())

    # - Act -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        ws.send_text(envelope("nobody.thing.happened"))
        reply = ws.receive_json()

    # - Assert -
    assert reply["type"] == "ws.error"
    assert reply["payload"]["code"] == "ws.unknown_type"


@pytest.mark.req("SYS-04-R14")
def test_connections_over_limit_close_4429(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Соединение сверх лимита пользователя закрывается `4429`."""
    # - Arrange -
    client = TestClient(ws_app(WsConfig(max_connections_per_user=2)))
    user_id = uuid4()

    # - Act / Assert -
    with client.websocket_connect("/ws", headers=bearer(user_id)) as first:
        first.send_text(envelope("ws.ping"))
        first.receive_json()
        with client.websocket_connect("/ws", headers=bearer(user_id)) as second:
            second.send_text(envelope("ws.ping"))
            second.receive_json()
            with (
                pytest.raises(WebSocketDisconnect) as closed,
                client.websocket_connect("/ws", headers=bearer(user_id)) as third,
            ):
                third.receive_json()
    assert closed.value.code == 4429


@pytest.mark.req("SYS-04-R14")
async def test_limiter_releases_slot() -> None:
    """Закрытие соединения освобождает слот: после `release` снова можно подключиться."""
    # - Arrange -
    limiter = ConnectionLimiter(ModuleRedis("shared_kernel"), limit=1)
    user_id = uuid4()

    # - Act -
    first = await limiter.acquire(user_id)
    over = await limiter.acquire(user_id)
    await limiter.release(user_id)
    again = await limiter.acquire(user_id)

    # - Assert -
    assert (first, over, again) == (True, False, True)


@pytest.mark.req("SYS-04-R11")
def test_server_pings_and_closes_silent_connection(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Сервер шлёт `ws.ping`; без входящих за `pong_timeout` закрывает `1011`."""
    # - Arrange -
    client = TestClient(ws_app(WsConfig(ping_interval_seconds=0.05, pong_timeout_seconds=0.12)))

    # - Act / Assert -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        assert ws.receive_json()["type"] == "ws.ping"
        while True:
            try:
                message = ws.receive_json()
            except WebSocketDisconnect as closed:
                assert closed.code == 1011
                assert closed.reason == "pong_timeout"
                break
            assert message["type"] == "ws.ping"
