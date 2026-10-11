"""WebSocket на стенде N3: событие с другого инстанса и остановка инстанса (SYS-05-R24, R26, R49; SYS-04-R18).

Клиент подключается напрямую к инстансу api №1; событие публикует процесс внутри контейнера
другого инстанса (`docker compose exec --index 2 api`) через `WsPublisher` — так, как это делает
код модуля на любом инстансе. Остановка инстанса с открытым соединением закрывает его кодом 1012.
"""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from tests.n_instances.stand import Instance, Stand
from tests.support.stand_keys import DEFAULT_PATH, load
from tests.support.tokens import access_claims, issue_access_token


pytestmark = pytest.mark.n_instances

RECEIVE_TIMEOUT_SECONDS = 15.0


def _headers(user_id: str) -> dict[str, str]:
    """`Authorization: Bearer` с access-токеном, подписанным ключом стенда."""
    pair = load(Path(os.environ.get("FLT_STAND_KEYS", DEFAULT_PATH)))
    return {"Authorization": f"Bearer {issue_access_token(pair, access_claims(user_id))}"}


async def _connect(instance: Instance, user_id: str) -> ClientConnection:
    """Соединение `/ws` напрямую с инстансом (мимо HAProxy) и проверка, что оно живо."""
    ws = await connect(instance.url.replace("http://", "ws://") + "/ws", additional_headers=_headers(user_id))
    await ws.send(
        json.dumps(
            {
                "type": "ws.ping",
                "correlation_id": str(uuid4()),
                "channel": None,
                "seq": 0,
                "ts": "2026-10-11T00:00:00.000Z",
                "payload": {},
            }
        )
    )
    reply = json.loads(await asyncio.wait_for(ws.recv(), RECEIVE_TIMEOUT_SECONDS))
    assert reply["type"] == "ws.pong"
    return ws


@pytest.mark.req("SYS-05-R24")
async def test_user_event_from_other_instance_reaches_client(stand: Stand, instances: list[Instance]) -> None:
    """Событие, опубликованное на инстансе 2, приходит клиенту, подключённому к инстансу 1."""
    # - Arrange -
    user_id = str(uuid4())
    first, second = instances[0], instances[1]
    ws = await _connect(first, user_id)
    script = (
        "import asyncio, uuid\n"
        "from app.core.ws.hub import WsPublisher\n"
        f"print(asyncio.run(WsPublisher().publish_to_user(uuid.UUID({user_id!r}), "
        "'probe.cross.instance', {'from': 'instance-2'})))\n"
    )

    # - Act -
    receivers = await stand.compose("exec", "-T", "--index", str(second.index), "api", "python", "-c", script)
    event = json.loads(await asyncio.wait_for(ws.recv(), RECEIVE_TIMEOUT_SECONDS))
    await ws.close()

    # - Assert -
    assert receivers.strip().splitlines()[-1] == "1"
    assert event["type"] == "probe.cross.instance"
    assert event["channel"] is None
    assert event["payload"] == {"from": "instance-2"}


@pytest.mark.req("SYS-05-R26")
async def test_stopped_instance_closes_websocket_1012(instances: list[Instance], stop_instance: object) -> None:
    """Остановка инстанса закрывает его соединения кодом 1012 `instance_shutdown`."""
    # - Arrange -
    target = instances[-1]
    ws = await _connect(target, str(uuid4()))

    # - Act -
    await stop_instance(target.container)  # type: ignore[operator]
    with pytest.raises(ConnectionClosed) as closed:
        await asyncio.wait_for(ws.recv(), RECEIVE_TIMEOUT_SECONDS)

    # - Assert -
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == 1012
    assert closed.value.rcvd.reason == "instance_shutdown"
