"""Инстанс, не прошедший проверку `/v1/ready`, исключается из балансировки и возвращается (ADR-012 §3.5).

Инстанс «зависает» (`docker pause flt-api-3`): процесс жив, DNS его по-прежнему отдаёт, но
проверка `GET /v1/ready` не получает ответа. HAProxy после `fall 3` неудачных проверок снимает
сервер с балансировки, запросы идут только на остальные инстансы; после снятия паузы и `rise 2`
успешных проверок сервер возвращается. Отказ по ответу 503 readiness (PostgreSQL недоступен у роли
`api`) проверяется на том же механизме после реализации readiness по ролям (Г.9, SYS-05-R41).
"""

from collections import Counter

import httpx
import pytest

from tests.n_instances.stand import INSTANCE_HEADER, ContainerAction, Instance, Stand


pytestmark = pytest.mark.n_instances

PROBE_PATH = "/api/v1/core-probe"
# Без ответа проверка длится до inter (2 с); три неудачи подряд — до ~12 с с запасом на DNS.
EXCLUDE_TIMEOUT_SECONDS = 20.0
RESTORE_TIMEOUT_SECONDS = 30.0
REQUESTS = 20


@pytest.mark.req("SYS-05-R41")
@pytest.mark.req("SYS-05-R44")
async def test_unready_instance_is_excluded_and_restored(
    stand: Stand,
    stand_client: httpx.AsyncClient,
    instances: list[Instance],
    pause_instance: ContainerAction,
) -> None:
    """Сервер без ответа на `/v1/ready` исключается из балансировки, после восстановления — возвращается."""
    # - Arrange -
    paused = next(instance for instance in instances if instance.index == 3)
    all_ids = {instance.instance_id for instance in instances}

    # - Act - инстанс перестаёт отвечать на проверки; запросы шлём только после исключения
    paused_ip = await pause_instance("flt-api-3")
    await stand.wait_server_down(paused_ip, within=EXCLUDE_TIMEOUT_SECONDS)
    while_excluded = [await stand_client.get(PROBE_PATH) for _ in range(REQUESTS)]

    await stand.docker("unpause", stand.container("flt-api-3"))
    await stand.wait_container_up(paused.container, within=RESTORE_TIMEOUT_SECONDS)
    restored = [await stand_client.get(PROBE_PATH) for _ in range(REQUESTS + 1)]

    # - Assert -
    assert all(response.status_code == 404 for response in [*while_excluded, *restored])
    assert set(Counter(r.headers[INSTANCE_HEADER] for r in while_excluded)) == all_ids - {paused.instance_id}
    assert {response.headers[INSTANCE_HEADER] for response in restored} == all_ids
