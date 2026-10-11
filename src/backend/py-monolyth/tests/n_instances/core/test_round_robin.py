"""Балансировка стенда N3: запросы через HAProxy распределяются по всем инстансам api (SYS-05-R4, R44)."""

from collections import Counter
from uuid import UUID

import httpx
import pytest

from tests.n_instances.stand import INSTANCE_HEADER, Instance, OnInstance, Stand


pytestmark = pytest.mark.n_instances

# Путь под /api/ без роутера: ответ 404 даёт сам монолит (с X-Instance-Id), не HAProxy.
PROBE_PATH = "/api/v1/core-probe"
EXPECTED_INSTANCES = 3
REQUESTS = 30


@pytest.mark.req("SYS-05-R4")
@pytest.mark.req("SYS-05-R44")
async def test_requests_through_haproxy_hit_all_instances(
    stand_client: httpx.AsyncClient, instances: list[Instance]
) -> None:
    """30 запросов одного клиента (keep-alive) через HAProxy попадают на все 3 инстанса поровну."""
    # - Act -
    responses = [await stand_client.get(PROBE_PATH) for _ in range(REQUESTS)]

    # - Assert -
    assert all(response.status_code == 404 for response in responses)
    hits = Counter(response.headers[INSTANCE_HEADER] for response in responses)
    assert set(hits) == {instance.instance_id for instance in instances}
    assert len(hits) == EXPECTED_INSTANCES
    # roundrobin без sticky-сессий: равномерно, а не «все запросы соединения — на один инстанс».
    assert all(count == REQUESTS // EXPECTED_INSTANCES for count in hits.values()), hits


@pytest.mark.req("SYS-05-R46")
async def test_instances_fixture_maps_direct_access(instances: list[Instance], on_instance: OnInstance) -> None:
    """`instances` — 3 разных инстанса; `on_instance(n)` обращается к n-му инстансу напрямую."""
    # - Act -
    response = await on_instance(2).get("/v1/health")

    # - Assert -
    assert len({instance.instance_id for instance in instances}) == EXPECTED_INSTANCES
    assert [instance.index for instance in instances] == [1, 2, 3]
    assert response.status_code == 200
    assert response.headers[INSTANCE_HEADER] == instances[1].instance_id


@pytest.mark.req("SYS-03-R20")
async def test_request_id_is_generated_by_haproxy(stand_client: httpx.AsyncClient) -> None:
    """HAProxy генерирует `X-Request-ID` (UUID) и не принимает клиентский (ADR-012 §3.4)."""
    # - Act -
    response = await stand_client.get(PROBE_PATH, headers={"X-Request-ID": "client-supplied"})

    # - Assert -
    request_id = response.headers["X-Request-ID"]
    assert request_id != "client-supplied"
    assert UUID(request_id).version == 4


@pytest.mark.req("SYS-05-R44")
@pytest.mark.parametrize("path", ["/v1/ready", "/v1/health", "/v1/metrics"])
async def test_service_endpoints_unreachable_through_haproxy(stand_client: httpx.AsyncClient, path: str) -> None:
    """Служебные `/v1/*` лежат вне `/api` и `/ws`: через HAProxy они до монолита не доходят."""
    # - Act -
    response = await stand_client.get(path)

    # - Assert -
    assert response.status_code == 404
    assert INSTANCE_HEADER not in response.headers


@pytest.mark.req("SYS-05-R44")
async def test_haproxy_sees_three_api_servers_up(stand: Stand, instances: list[Instance]) -> None:
    """В `stats;csv` HAProxy ровно 3 сервера `be_api` в состоянии UP — по одному на инстанс."""
    # - Act -
    up = await stand.up_servers()

    # - Assert -
    ips = {await stand.container_ip(instance.container) for instance in instances}
    assert {server.ip for server in up} == ips
    assert len(up) == EXPECTED_INSTANCES
