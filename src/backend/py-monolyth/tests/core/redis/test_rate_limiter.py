"""Тесты ограничителя `ModuleRedis.rate_limiter` (скользящее окно на ZSET в Lua; ADR-003, SYS-03-R19, SYS-05)."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from prometheus_client import REGISTRY
from redis.asyncio import Redis

from app.core.dao.caching import ModuleRedis, RedisUnavailableError


@pytest.mark.req("SYS-03-R19")
async def test_limit_counts_hits_in_window(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """`limit` попыток разрешены, следующая отклоняется с `retry_after` в пределах окна."""
    # - Act -
    results = [
        await module_redis.rate_limiter.hit(
            "probe", "s1", limit=3, window=timedelta(seconds=10), on_unavailable="fail_closed"
        )
        for _ in range(4)
    ]

    # - Assert -
    assert [r.allowed for r in results] == [True, True, True, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0]
    denied = results[-1]
    assert timedelta(0) < denied.retry_after <= timedelta(seconds=10)
    assert 1 <= denied.retry_after_seconds <= 10
    assert 0 < await raw_test_redis.pttl("shared_kernel:ratelimit:probe:s1") <= 10_000


@pytest.mark.req("SYS-03-R19")
async def test_window_slides(module_redis: ModuleRedis) -> None:
    """После истечения окна попытки снова разрешены; субъекты считаются раздельно."""
    # - Arrange -
    window = timedelta(milliseconds=300)
    await module_redis.rate_limiter.hit("probe", "s1", limit=1, window=window, on_unavailable="fail_closed")

    # - Act -
    denied = await module_redis.rate_limiter.hit("probe", "s1", limit=1, window=window, on_unavailable="fail_closed")
    other = await module_redis.rate_limiter.hit("probe", "s2", limit=1, window=window, on_unavailable="fail_closed")
    await asyncio.sleep(0.35)
    again = await module_redis.rate_limiter.hit("probe", "s1", limit=1, window=window, on_unavailable="fail_closed")

    # - Assert -
    assert denied.allowed is False
    assert other.allowed is True
    assert again.allowed is True


@pytest.mark.req("SYS-05-R51")
async def test_rate_limit_is_global_across_instances(redis_instances: Callable[[], Redis]) -> None:
    """Лимит `L` исчерпывается конкурентными попытками с трёх инстансов: разрешено ровно `L`."""
    # - Arrange -
    instances = [ModuleRedis("shared_kernel", client=redis_instances()) for _ in range(3)]
    limit = 10

    # - Act -
    results = await asyncio.gather(
        *(
            instances[i % 3].rate_limiter.hit(
                "probe", "global", limit=limit, window=timedelta(seconds=10), on_unavailable="fail_closed"
            )
            for i in range(30)
        )
    )

    # - Assert -
    assert sum(r.allowed for r in results) == limit
    assert all(r.retry_after > timedelta(0) for r in results if not r.allowed)


@pytest.mark.req("SYS-05-R13")
async def test_window_above_24h_rejected(module_redis: ModuleRedis) -> None:
    """Окно лимита больше 24 часов и непозитивный лимит отклоняются."""
    with pytest.raises(ValueError, match="ttl"):
        await module_redis.rate_limiter.hit(
            "probe", "s", limit=1, window=timedelta(hours=25), on_unavailable="fail_closed"
        )
    with pytest.raises(ValueError, match="limit"):
        await module_redis.rate_limiter.hit(
            "probe", "s", limit=0, window=timedelta(seconds=1), on_unavailable="fail_closed"
        )


@pytest.mark.req("SYS-05-R15")
async def test_fail_open_without_redis_counts_bypass(down_redis: ModuleRedis) -> None:
    """Политика fail-open: без Redis запрос пропускается и растёт `flt_ratelimit_bypassed_total`."""
    # - Arrange -
    labels = {"module": "shared_kernel", "scope": "probe_open"}
    before = REGISTRY.get_sample_value("flt_ratelimit_bypassed_total", labels) or 0.0

    # - Act -
    result = await down_redis.rate_limiter.hit(
        "probe_open", "s", limit=1, window=timedelta(seconds=1), on_unavailable="fail_open"
    )

    # - Assert -
    assert result.allowed is True
    assert result.bypassed is True
    assert REGISTRY.get_sample_value("flt_ratelimit_bypassed_total", labels) == before + 1


@pytest.mark.req("SYS-05-R15")
async def test_fail_closed_without_redis_raises(down_redis: ModuleRedis) -> None:
    """Политика fail-closed: без Redis — `RedisUnavailableError` (HTTP-слой отдаёт 503)."""
    with pytest.raises(RedisUnavailableError):
        await down_redis.rate_limiter.hit(
            "probe_closed", "s", limit=1, window=timedelta(seconds=1), on_unavailable="fail_closed"
        )
