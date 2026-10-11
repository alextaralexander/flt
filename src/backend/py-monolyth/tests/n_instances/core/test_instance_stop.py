"""Остановка инстанса посреди сценария: стенд продолжает обслуживать запросы (SYS-05-R52, R41).

`docker stop flt-api-2` (SIGTERM): uvicorn перестаёт принимать соединения, проверки HAProxy
получают отказ и снимают сервер с балансировки (`fall 3` × `inter 2s`); запросы, успевшие уйти на
остановленный инстанс до этого, HAProxy повторяет на другом (`option redispatch`, `retries 2`).
Teardown фикстуры `stop_instance` запускает контейнер и ждёт его возвращения в балансировку.
"""

import asyncio
from collections import Counter

import httpx
import pytest

from tests.n_instances.stand import INSTANCE_HEADER, ContainerAction, Instance, Stand


pytestmark = pytest.mark.n_instances

PROBE_PATH = "/api/v1/core-probe"
# SYS-05-R41: после остановки сервер в состоянии DOWN не позднее 10 с.
EXCLUDE_TIMEOUT_SECONDS = 10.0
REQUESTS_AFTER_STOP = 20


@pytest.mark.smoke
@pytest.mark.req("SYS-05-R52")
@pytest.mark.req("SYS-05-R41")
async def test_requests_survive_instance_stop(
    stand: Stand,
    stand_client: httpx.AsyncClient,
    instances: list[Instance],
    stop_instance: ContainerAction,
) -> None:
    """Сценарий через HAProxy не прерывается: остановленный flt-api-2 исключается, остальные отвечают."""
    # - Arrange -
    stopped = next(instance for instance in instances if instance.index == 2)
    before = await stand_client.get(PROBE_PATH)
    assert before.status_code == 404

    # - Act - остановка посреди сценария, запросы идут, пока HAProxy не исключит сервер
    stopped_ip = await stop_instance("flt-api-2")
    during = await _requests_until_excluded(stand, stand_client, stopped_ip)
    after = [await stand_client.get(PROBE_PATH) for _ in range(REQUESTS_AFTER_STOP)]

    # - Assert -
    assert all(response.status_code == 404 for response in [*during, *after]), [r.status_code for r in during]
    hits = Counter(response.headers[INSTANCE_HEADER] for response in after)
    survivors = {instance.instance_id for instance in instances} - {stopped.instance_id}
    assert set(hits) == survivors
    assert stopped.instance_id not in {response.headers[INSTANCE_HEADER] for response in during}


async def _requests_until_excluded(stand: Stand, client: httpx.AsyncClient, ip: str) -> list[httpx.Response]:
    """Шлёт запросы через HAProxy, пока сервер `ip` не исключён (не дольше 10 с), и возвращает ответы."""
    responses: list[httpx.Response] = []

    async def traffic() -> None:
        while True:
            responses.append(await client.get(PROBE_PATH))
            await asyncio.sleep(0.2)

    sender = asyncio.create_task(traffic())
    try:
        await stand.wait_server_down(ip, within=EXCLUDE_TIMEOUT_SECONDS)
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
    return responses
