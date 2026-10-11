"""Каналы `/ws`, команды модулей и доставка событий между инстансами (SYS-04-R6…R8, R13, R18; SYS-05-R24)."""

import asyncio
from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.ws.hub import WsHub, WsPublisher
from app.core.ws.protocol import WsConfig
from tests.core.ws.conftest import envelope


Bearer = Callable[..., dict[str, str]]


def _subscribe(ws: object, channel: str) -> dict[str, object]:
    """Подписка и ответ сервера."""
    ws.send_text(envelope("ws.subscribe", {"channel": channel}))  # type: ignore[attr-defined]
    return ws.receive_json()  # type: ignore[attr-defined,no-any-return]


@pytest.mark.req("SYS-04-R6")
def test_subscribe_ack_with_state_url_and_unsubscribe(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Подписка → `ws.ack` со `state_url`; повторная — тоже ack; отписка → ack `unsubscribe`."""
    # - Arrange -
    client = TestClient(ws_app())

    # - Act -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        ack = _subscribe(ws, "probe_mod.room:42")
        repeated = _subscribe(ws, "probe_mod.room:42")
        ws.send_text(envelope("ws.unsubscribe", {"channel": "probe_mod.room:42"}))
        unsubscribed = ws.receive_json()

    # - Assert -
    assert ack["type"] == "ws.ack"
    assert ack["payload"] == {
        "op": "subscribe",
        "channel": "probe_mod.room:42",
        "state_url": "/api/v1/probe-mod/rooms/42",
    }
    assert repeated["type"] == "ws.ack"
    assert unsubscribed["payload"] == {"op": "unsubscribe", "channel": "probe_mod.room:42"}


@pytest.mark.req("SYS-04-R7")
@pytest.mark.parametrize(
    ("channel", "code"),
    [
        ("probe_mod.room:secret", "ws.forbidden"),
        ("other_mod.room:1", "ws.unknown_channel"),
        ("Not A Channel", "ws.invalid_channel"),
    ],
)
def test_subscription_rejections(ws_app: Callable[..., FastAPI], bearer: Bearer, channel: str, code: str) -> None:
    """Право проверяет обработчик модуля; нет обработчика или неверное имя — свои коды ошибок."""
    # - Arrange -
    client = TestClient(ws_app())

    # - Act -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        reply = _subscribe(ws, channel)

    # - Assert -
    assert reply["type"] == "ws.error"
    assert reply["payload"]["code"] == code  # type: ignore[index]


@pytest.mark.req("SYS-04-R14")
def test_subscription_limit(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Подписка сверх лимита соединения — `ws.subscription_limit`."""
    # - Arrange -
    client = TestClient(ws_app(WsConfig(max_subscriptions_per_connection=1)))

    # - Act -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        _subscribe(ws, "probe_mod.room:1")
        reply = _subscribe(ws, "probe_mod.room:2")

    # - Assert -
    assert reply["payload"]["code"] == "ws.subscription_limit"  # type: ignore[index]


@pytest.mark.req("SYS-04-R8")
def test_module_command_goes_to_handler(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Команда модуля передаётся обработчику с тем же correlation_id."""
    # - Arrange -
    client = TestClient(ws_app())
    correlation_id = str(uuid4())

    # - Act -
    with client.websocket_connect("/ws", headers=bearer()) as ws:
        ws.send_text(envelope("probe_mod.room.echo", {"text": "hi"}, correlation_id=correlation_id))
        reply = ws.receive_json()

    # - Assert -
    assert reply["type"] == "probe_mod.room.echoed"
    assert reply["payload"] == {"text": "hi"}
    assert reply["correlation_id"] == correlation_id


@pytest.mark.req("SYS-05-R24")
async def test_channel_event_from_another_instance_is_delivered(
    ws_app: Callable[..., FastAPI], bearer: Bearer, raw_test_redis: Redis
) -> None:
    """Событие, опубликованное другим процессом через Redis, доходит до подписчика этого инстанса."""
    # - Arrange -
    client = TestClient(ws_app())
    publisher = WsPublisher(redis_factory=lambda: _ready(raw_test_redis))

    with client.websocket_connect("/ws", headers=bearer()) as ws:
        _subscribe(ws, "probe_mod.room:7")

        # - Act -
        receivers = await publisher.publish("probe_mod.room:7", "probe_mod.room.changed", {"n": 1})
        event = ws.receive_json()

    # - Assert -
    assert receivers == 1
    assert event["type"] == "probe_mod.room.changed"
    assert event["channel"] == "probe_mod.room:7"
    assert event["payload"] == {"n": 1}


@pytest.mark.req("SYS-04-R13")
async def test_user_event_reaches_all_connections_of_user(
    ws_app: Callable[..., FastAPI], bearer: Bearer, raw_test_redis: Redis
) -> None:
    """Адресное событие пользователя приходит во все его соединения без подписки, `channel: null`."""
    # - Arrange -
    client = TestClient(ws_app())
    publisher = WsPublisher(redis_factory=lambda: _ready(raw_test_redis))
    user_id = uuid4()

    with (
        client.websocket_connect("/ws", headers=bearer(user_id)) as first,
        client.websocket_connect("/ws", headers=bearer(user_id)) as second,
    ):
        for ws in (first, second):
            ws.send_text(envelope("ws.ping"))
            ws.receive_json()

        # - Act -
        await publisher.publish_to_user(user_id, "notifications.item.created", {"id": "x"})
        events = [first.receive_json(), second.receive_json()]

    # - Assert -
    assert [(event["type"], event["channel"]) for event in events] == [("notifications.item.created", None)] * 2


@pytest.mark.req("SYS-04-R18")
def test_hub_stop_closes_connections_1012(ws_app: Callable[..., FastAPI], bearer: Bearer) -> None:
    """Остановка инстанса закрывает соединения кодом `1012 instance_shutdown`."""
    # - Arrange -
    application = ws_app()
    hub: WsHub = application.state.ws_hub

    # - Act / Assert -
    with TestClient(application) as client, client.websocket_connect("/ws", headers=bearer()) as ws:
        ws.send_text(envelope("ws.ping"))
        ws.receive_json()
        assert client.portal is not None
        client.portal.call(hub.stop)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1012


async def _ready(redis: Redis) -> Redis:
    """Фабрика клиента для `WsPublisher`."""
    await asyncio.sleep(0)
    return redis
