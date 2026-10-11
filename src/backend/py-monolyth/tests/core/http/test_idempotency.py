"""Интеграционные тесты идемпотентности `POST` по `Idempotency-Key` с реальным Redis (SYS-03-R18).

Несколько экземпляров приложения с независимыми клиентами Redis имитируют инстансы монолита
за HAProxy: повтор запроса на другой инстанс должен вернуть сохранённый ответ, а одновременные
одинаковые запросы — выполниться один раз.
"""

import asyncio
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request, Response
from httpx import AsyncClient
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.dao.caching import ModuleRedis
from app.core.http.context import set_request_user
from app.core.http.deps import Idempotent
from app.main import create_app


URL = "/api/v1/core-test/probes"


class ProbeCreateRequest(BaseModel):
    """Тело создания тестового ресурса."""

    title: str


class Calls:
    """Счётчик выполнений обработчика (общий для всех «инстансов» теста)."""

    def __init__(self, delay: float = 0.0, fail_first: bool = False) -> None:
        """Задаёт задержку обработчика и необходимость упасть в первый раз."""
        self.count = 0
        self.delay = delay
        self.fail_first = fail_first


async def _test_user(request: Request) -> None:
    """Тестовая аутентификация: пользователь из заголовка `X-Test-User`."""
    user_id = request.headers.get("X-Test-User")
    if user_id:
        set_request_user(request, SimpleNamespace(user_id=user_id))


def build_instance(redis: ModuleRedis, calls: Calls) -> FastAPI:
    """Экземпляр приложения («инстанс») с создающим роутом под `Idempotent()`."""
    app = create_app()

    @app.post(URL, status_code=201, dependencies=[Depends(_test_user)])
    async def create_probe(
        body: ProbeCreateRequest,
        response: Response,
        key: Annotated[uuid.UUID, Depends(Idempotent(redis))],
    ) -> dict[str, object]:
        calls.count += 1
        if calls.delay:
            await asyncio.sleep(calls.delay)
        if calls.fail_first and calls.count == 1:
            raise RuntimeError("provider failed")
        probe_id = str(uuid.uuid4())
        response.headers["Location"] = f"{URL}/{probe_id}"
        return {"id": probe_id, "title": body.title, "call": calls.count}

    return app


@pytest.fixture
def instances(redis_instances: Callable[[], Redis]) -> Callable[..., list[FastAPI]]:
    """Фабрика N «инстансов» приложения с отдельными клиентами Redis."""

    def factory(count: int, calls: Calls) -> list[FastAPI]:
        return [build_instance(ModuleRedis("shared_kernel", client=redis_instances()), calls) for _ in range(count)]

    return factory


def _headers(key: str, user: str | None = "u1", **extra: str) -> dict[str, str]:
    """Заголовки запроса с ключом идемпотентности и тестовым пользователем."""
    headers = {"Idempotency-Key": key, **extra}
    if user:
        headers["X-Test-User"] = user
    return headers


@pytest.mark.req("SYS-03-R18")
async def test_replay_returns_saved_response(
    instances: Callable[..., list[FastAPI]],
    client_factory: Callable[..., AsyncClient],
    raw_test_redis: Redis,
) -> None:
    """Повтор с тем же ключом и телом на другом инстансе — сохранённый ответ, обработчик выполнен один раз."""
    # - Arrange -
    calls = Calls()
    first_app, second_app = instances(2, calls)
    key = str(uuid.uuid4())

    # - Act -
    async with client_factory(first_app) as first, client_factory(second_app) as second:
        created = await first.post(URL, json={"title": "a"}, headers=_headers(key))
        replayed = await second.post(URL, json={"title": "a"}, headers=_headers(key))

    # - Assert -
    assert created.status_code == 201
    assert "Idempotent-Replayed" not in created.headers
    assert replayed.status_code == 201
    assert replayed.headers["Idempotent-Replayed"] == "true"
    assert replayed.json() == created.json()
    assert replayed.headers["Location"] == created.headers["Location"]
    assert replayed.headers["Content-Type"] == created.headers["Content-Type"]
    assert calls.count == 1
    redis_key = f"shared_kernel:idempotency:user:u1:{key}"
    assert 23 * 3600 < await raw_test_redis.ttl(redis_key) <= 24 * 3600


@pytest.mark.req("SYS-03-R18")
async def test_same_key_other_body_rejected(
    instances: Callable[..., list[FastAPI]], client_factory: Callable[..., AsyncClient]
) -> None:
    """Тот же ключ с другим телом — `422 core.idempotency_key_reused`; порядок ключей JSON не важен."""
    # - Arrange -
    calls = Calls()
    (app,) = instances(1, calls)
    key = str(uuid.uuid4())

    # - Act -
    async with client_factory(app) as client:
        await client.post(URL, content=b'{"title": "a"}', headers=_headers(key, **{"Content-Type": "application/json"}))
        same = await client.post(
            URL, content=b'{ "title":"a" }', headers=_headers(key, **{"Content-Type": "application/json"})
        )
        other = await client.post(URL, json={"title": "b"}, headers=_headers(key))

    # - Assert -
    assert same.headers["Idempotent-Replayed"] == "true"
    assert other.status_code == 422
    assert other.json()["messages"]["ERROR"][0]["code"] == "core.idempotency_key_reused"
    assert calls.count == 1


@pytest.mark.req("SYS-03-R18")
async def test_retry_in_progress_conflict(
    instances: Callable[..., list[FastAPI]], client_factory: Callable[..., AsyncClient]
) -> None:
    """Повтор во время выполнения первого запроса — `409 core.request_in_progress` с `Retry-After: 1`."""
    # - Arrange -
    calls = Calls(delay=0.3)
    first_app, second_app = instances(2, calls)
    key = str(uuid.uuid4())

    # - Act -
    async with client_factory(first_app) as first, client_factory(second_app) as second:
        first_task = asyncio.create_task(first.post(URL, json={"title": "a"}, headers=_headers(key)))
        await asyncio.sleep(0.1)
        in_progress = await second.post(URL, json={"title": "a"}, headers=_headers(key))
        created = await first_task

    # - Assert -
    assert created.status_code == 201
    assert in_progress.status_code == 409
    assert in_progress.headers["Retry-After"] == "1"
    assert in_progress.json()["messages"]["ERROR"][0]["code"] == "core.request_in_progress"


@pytest.mark.req("SYS-03-R18")
@pytest.mark.req("SYS-05-R48")
async def test_concurrent_requests_on_instances_execute_once(
    instances: Callable[..., list[FastAPI]], client_factory: Callable[..., AsyncClient]
) -> None:
    """Одновременные одинаковые `POST` на три инстанса создают один ресурс; остальные — 409 или повтор."""
    # - Arrange -
    calls = Calls(delay=0.05)
    apps = instances(3, calls)
    key = str(uuid.uuid4())
    clients = [client_factory(app) for app in apps]

    # - Act -
    responses = await asyncio.gather(
        *(client.post(URL, json={"title": "a"}, headers=_headers(key)) for client in clients * 2)
    )
    for client in clients:
        await client.aclose()

    # - Assert -
    assert calls.count == 1
    statuses = sorted(r.status_code for r in responses)
    assert statuses.count(201) >= 1
    assert set(statuses) <= {201, 409}
    created_ids = {r.json()["id"] for r in responses if r.status_code == 201}
    assert len(created_ids) == 1


@pytest.mark.req("SYS-03-R18")
async def test_subjects_are_isolated(
    instances: Callable[..., list[FastAPI]], client_factory: Callable[..., AsyncClient]
) -> None:
    """Один и тот же ключ разных пользователей и анонимных сессий — разные записи."""
    # - Arrange -
    calls = Calls()
    (app,) = instances(1, calls)
    key = str(uuid.uuid4())

    # - Act -
    async with client_factory(app) as client:
        await client.post(URL, json={"title": "a"}, headers=_headers(key, user="u1"))
        await client.post(URL, json={"title": "a"}, headers=_headers(key, user="u2"))
        anon = _headers(key, user=None, Cookie="flt_anon_session=s1")
        await client.post(URL, json={"title": "a"}, headers=anon)
        replay = await client.post(URL, json={"title": "a"}, headers=anon)
        await client.post(URL, json={"title": "a"}, headers=_headers(key, user=None, Cookie="flt_anon_session=s2"))

    # - Assert -
    assert calls.count == 4
    assert replay.headers["Idempotent-Replayed"] == "true"


@pytest.mark.req("SYS-03-R18")
async def test_key_header_required_and_uuid(
    instances: Callable[..., list[FastAPI]], client_factory: Callable[..., AsyncClient]
) -> None:
    """Без `Idempotency-Key` или с не-UUID значением — `422 core.validation_failed`, обработчик не вызван."""
    # - Arrange -
    calls = Calls()
    (app,) = instances(1, calls)

    # - Act -
    async with client_factory(app) as client:
        missing = await client.post(URL, json={"title": "a"}, headers={"X-Test-User": "u1"})
        invalid = await client.post(URL, json={"title": "a"}, headers=_headers("not-a-uuid"))

    # - Assert -
    for response in (missing, invalid):
        assert response.status_code == 422
        assert response.json()["messages"]["ERROR"][0]["code"] == "core.validation_failed"
    assert calls.count == 0


@pytest.mark.req("SYS-03-R18")
async def test_server_error_is_not_saved(
    instances: Callable[..., list[FastAPI]], client_factory: Callable[..., AsyncClient]
) -> None:
    """Ответ `5xx` не сохраняется: повтор выполняется заново."""
    # - Arrange -
    calls = Calls(fail_first=True)
    (app,) = instances(1, calls)
    key = str(uuid.uuid4())

    # - Act -
    async with client_factory(app) as client:
        failed = await client.post(URL, json={"title": "a"}, headers=_headers(key))
        retried = await client.post(URL, json={"title": "a"}, headers=_headers(key))

    # - Assert -
    assert failed.status_code == 500
    assert retried.status_code == 201
    assert "Idempotent-Replayed" not in retried.headers
    assert calls.count == 2


@pytest.mark.req("SYS-03-R18")
@pytest.mark.req("SYS-05-R15")
async def test_redis_down_executes_without_idempotency(
    redis_down: None, client_factory: Callable[..., AsyncClient]
) -> None:
    """Без Redis запрос выполняется (fail-open): повтор выполняется заново."""
    # - Arrange -
    calls = Calls()
    app = build_instance(ModuleRedis("shared_kernel"), calls)
    key = str(uuid.uuid4())

    # - Act -
    async with client_factory(app) as client:
        first = await client.post(URL, json={"title": "a"}, headers=_headers(key))
        second = await client.post(URL, json={"title": "a"}, headers=_headers(key))

    # - Assert -
    assert (first.status_code, second.status_code) == (201, 201)
    assert calls.count == 2
