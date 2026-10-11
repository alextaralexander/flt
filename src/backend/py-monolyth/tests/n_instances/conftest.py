"""Фикстуры стенда N3 (SYS-05-R46): HAProxy, инстансы роли api, остановка и пауза контейнеров.

Тесты этого каталога помечаются `n_instances` и запускаются только с `--stand-url`
(`make stand-test`, `make test-n3`); без опции они пропускаются (хук в `tests/conftest.py`).
Фикстуры, меняющие стенд (`stop_instance`, `pause_instance`), в teardown возвращают контейнер
и ждут его состояния UP в HAProxy, чтобы следующий тест получил стенд из N инстансов.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from tests.n_instances.stand import (
    HTTP_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    ContainerAction,
    Instance,
    OnInstance,
    Stand,
)
from tests.support.eventually import eventually


# Возврат остановленного инстанса: старт приложения, rise 2 проверок HAProxy и DNS (ADR-012 §3.5).
RESTORE_TIMEOUT_SECONDS = 60.0


@pytest.fixture(scope="session")
def stand(request: pytest.FixtureRequest) -> Stand:
    """Стенд N3: адрес HAProxy (`--stand-url`) и проект compose (`--stand-project`)."""
    url = request.config.getoption("--stand-url")
    assert url, "нужен стенд N3: передайте --stand-url"
    return Stand(url=url, project=request.config.getoption("--stand-project"))


@pytest_asyncio.fixture
async def stand_client(stand: Stand) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент с cookie-jar, который ходит на стенд через HAProxy."""
    async with httpx.AsyncClient(base_url=stand.url, timeout=HTTP_TIMEOUT_SECONDS) as client:
        yield client


@pytest_asyncio.fixture
async def instances(stand: Stand) -> list[Instance]:
    """Работающие инстансы роли api по номеру реплики (адрес прямого доступа и `X-Instance-Id`).

    Перед тестом ждёт, пока HAProxy держит в балансировке каждый работающий инстанс: тест
    начинается на полном стенде, даже если предыдущий только что вернул остановленный контейнер.
    """
    current = await stand.instances()

    async def all_up() -> bool:
        return len(await stand.up_servers()) == len(current)

    await eventually(all_up, timeout=RESTORE_TIMEOUT_SECONDS, interval=POLL_INTERVAL_SECONDS)
    return current


@pytest_asyncio.fixture
async def on_instance(instances: list[Instance]) -> AsyncIterator[OnInstance]:
    """`on_instance(n)` — HTTP-клиент, обращающийся напрямую к n-му инстансу api, мимо HAProxy."""
    clients: dict[int, httpx.AsyncClient] = {}
    by_index = {instance.index: instance for instance in instances}

    def client_for(index: int) -> httpx.AsyncClient:
        if index not in clients:
            clients[index] = httpx.AsyncClient(base_url=by_index[index].url, timeout=HTTP_TIMEOUT_SECONDS)
        return clients[index]

    yield client_for
    for client in clients.values():
        await client.aclose()


@pytest_asyncio.fixture
async def stop_instance(stand: Stand) -> AsyncIterator[ContainerAction]:
    """Остановка контейнера стенда (`docker stop`, например flt-api-2); действие возвращает его IP.

    Teardown запускает контейнер и для инстанса api ждёт его состояния UP в HAProxy.
    """
    stopped: list[str] = []

    async def stop(name: str) -> str:
        container = stand.container(name)
        ip = await stand.container_ip(container)
        await stand.docker("stop", container)
        stopped.append(container)
        return ip

    yield stop
    for container in stopped:
        await stand.docker("start", container)
        # За HAProxy стоят только инстансы api; воркеру достаточно запуска (SYS-05-R31).
        if "-api-" in container:
            await stand.wait_container_up(container, within=RESTORE_TIMEOUT_SECONDS)


@pytest_asyncio.fixture
async def pause_instance(stand: Stand) -> AsyncIterator[ContainerAction]:
    """Пауза контейнера стенда (`docker pause`, например flt-api-3): инстанс жив, но не отвечает.

    Teardown снимает паузу и ждёт, пока HAProxy вернёт сервер в балансировку.
    """
    paused: list[str] = []

    async def pause(name: str) -> str:
        container = stand.container(name)
        ip = await stand.container_ip(container)
        await stand.docker("pause", container)
        paused.append(container)
        return ip

    yield pause
    for container in paused:
        # Тест мог снять паузу сам (проверка возврата в балансировку).
        if (await stand.docker("inspect", "-f", "{{.State.Paused}}", container)).strip() == "true":
            await stand.docker("unpause", container)
        await stand.wait_container_up(container, within=RESTORE_TIMEOUT_SECONDS)
