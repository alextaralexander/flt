"""Ответ `429` по лимиту shared kernel через несколько «инстансов» (SYS-03-R19, SYS-05-R51)."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient
from redis.asyncio import Redis

from app.core.dao.caching import ModuleRedis
from app.core.http.errors import RateLimitedError
from app.main import create_app


LIMIT = 5


def build_instance(redis: ModuleRedis) -> FastAPI:
    """«Инстанс» с роутом, ограниченным `LIMIT` запросами в минуту с одного IP."""
    app = create_app()

    @app.get("/api/v1/core-test/limited")
    async def limited(request: Request) -> dict[str, bool]:
        subject = request.client.host if request.client else "unknown"
        result = await redis.rate_limiter.hit(
            "probe", subject, limit=LIMIT, window=timedelta(minutes=1), on_unavailable="fail_open"
        )
        if not result.allowed:
            raise RateLimitedError.from_result(result, scope="probe")
        return {"ok": True}

    return app


@pytest.mark.req("SYS-03-R19")
@pytest.mark.req("SYS-05-R51")
async def test_rate_limit_is_global_and_returns_429(
    redis_instances: Callable[[], Redis], client_factory: Callable[..., AsyncClient], raw_test_redis: Redis
) -> None:
    """Лимит исчерпывается запросами на три инстанса; лишние получают `429` с `Retry-After` на любом инстансе."""
    # - Arrange -
    apps = [build_instance(ModuleRedis("shared_kernel", client=redis_instances())) for _ in range(3)]
    clients = [client_factory(app) for app in apps]

    # - Act -
    responses = await asyncio.gather(*(clients[i % 3].get("/api/v1/core-test/limited") for i in range(12)))
    for client in clients:
        await client.aclose()

    # - Assert -
    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == LIMIT
    assert statuses.count(429) == 12 - LIMIT
    denied = next(r for r in responses if r.status_code == 429)
    assert 1 <= int(denied.headers["Retry-After"]) <= 60
    error = denied.json()["messages"]["ERROR"][0]
    assert error["code"] == "core.rate_limited"
    assert error["details"] == {"scope": "probe", "retry_after_seconds": int(denied.headers["Retry-After"])}
    assert await raw_test_redis.exists("shared_kernel:ratelimit:probe:127.0.0.1") == 1
