"""Тесты распределённых блокировок `ModuleRedis.locks` с реальным Redis (ADR-003, SYS-05-R20)."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from redis.asyncio import Redis

from app.core.dao.caching import LockNotAcquiredError, ModuleRedis, RedisUnavailableError


def _instances(redis_instances: Callable[[], Redis], count: int) -> list[ModuleRedis]:
    """`ModuleRedis` одного модуля на `count` независимых клиентах (имитация инстансов)."""
    return [ModuleRedis("shared_kernel", client=redis_instances()) for _ in range(count)]


@pytest.mark.req("SYS-05-R20")
async def test_second_acquire_fails_until_ttl(redis_instances: Callable[[], Redis], raw_test_redis: Redis) -> None:
    """Блокировку, взятую инстансом A, инстанс B не получает, пока она не истечёт или не будет снята."""
    # - Arrange -
    a, b = _instances(redis_instances, 2)

    # - Act / Assert -
    async with a.locks.acquire("job", ttl=timedelta(milliseconds=300)) as lock:
        assert await raw_test_redis.get("shared_kernel:lock:job") == lock.token
        assert 0 < await raw_test_redis.pttl("shared_kernel:lock:job") <= 300
        with pytest.raises(LockNotAcquiredError):
            async with b.locks.acquire("job", ttl=timedelta(seconds=1)):
                pass
        await asyncio.sleep(0.35)
        async with b.locks.acquire("job", ttl=timedelta(seconds=1)):
            pass
        assert await lock.release() is False


@pytest.mark.req("SYS-05-R20")
async def test_release_ignores_foreign_token(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """Освобождение с чужим токеном не снимает блокировку другого владельца."""
    # - Arrange -
    async with module_redis.locks.acquire("job", ttl=timedelta(seconds=5)) as lock:
        await raw_test_redis.set("shared_kernel:lock:job", "foreign-token", px=5000)

        # - Act -
        released = await lock.release()

        # - Assert -
        assert released is False
        assert await raw_test_redis.get("shared_kernel:lock:job") == "foreign-token"


@pytest.mark.req("SYS-05-R20")
async def test_extend_requires_token(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """Продление работает только для владельца: после перехвата блокировки `extend` возвращает `False`."""
    async with module_redis.locks.acquire("job", ttl=timedelta(seconds=2)) as lock:
        # - Act / Assert -
        assert await lock.extend(timedelta(seconds=10)) is True
        assert await raw_test_redis.pttl("shared_kernel:lock:job") > 2000
        await raw_test_redis.set("shared_kernel:lock:job", "foreign-token", px=5000)
        assert await lock.extend(timedelta(seconds=10)) is False


@pytest.mark.req("SYS-05-R20")
async def test_lock_expires_without_heartbeat(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """Без продления блокировка истекает сама; с heartbeat — живёт дольше исходного TTL."""
    # - Act -
    async with module_redis.locks.acquire("plain", ttl=timedelta(milliseconds=200)):
        await asyncio.sleep(0.3)
        plain_exists = await raw_test_redis.exists("shared_kernel:lock:plain")
    async with module_redis.locks.acquire("beat", ttl=timedelta(milliseconds=300), heartbeat=True):
        await asyncio.sleep(0.7)
        beat_exists = await raw_test_redis.exists("shared_kernel:lock:beat")

    # - Assert -
    assert plain_exists == 0
    assert beat_exists == 1
    assert await raw_test_redis.exists("shared_kernel:lock:beat") == 0


@pytest.mark.req("SYS-05-R13")
async def test_lock_ttl_above_60s_requires_extend(module_redis: ModuleRedis) -> None:
    """TTL блокировки больше 60 с отклоняется: длинные задачи продлевают блокировку heartbeat-ом."""
    with pytest.raises(ValueError, match="60"):
        async with module_redis.locks.acquire("job", ttl=timedelta(seconds=61)):
            pass
    async with module_redis.locks.acquire("job", ttl=timedelta(seconds=10)) as lock:
        with pytest.raises(ValueError, match="60"):
            await lock.extend(timedelta(seconds=61))


@pytest.mark.req("SYS-05-R13")
async def test_schedule_lock_may_live_for_task_interval(redis_instances: Callable[[], Redis]) -> None:
    """Блокировка планировщика `shared_kernel:lock:schedule:*` может держаться интервал задачи (до 24 ч)."""
    # - Arrange -
    shared_kernel = ModuleRedis("shared_kernel", client=redis_instances())

    # - Act / Assert -
    async with shared_kernel.locks.acquire("schedule:identity.purge_tokens", ttl=timedelta(hours=1)):
        pass
    with pytest.raises(ValueError, match="86400"):
        async with shared_kernel.locks.acquire("schedule:identity.purge_tokens", ttl=timedelta(hours=25)):
            pass


@pytest.mark.req("SYS-05-R20")
@pytest.mark.req("SYS-05-R51")
async def test_concurrent_acquire_single_winner(redis_instances: Callable[[], Redis]) -> None:
    """Одновременная попытка трёх инстансов взять блокировку: критическую секцию выполняет ровно один."""
    # - Arrange -
    instances = _instances(redis_instances, 3)
    entered: list[int] = []

    async def worker(index: int, redis: ModuleRedis) -> bool:
        try:
            async with redis.locks.acquire("critical", ttl=timedelta(seconds=5)):
                entered.append(index)
                await asyncio.sleep(0.1)
                return True
        except LockNotAcquiredError:
            return False

    # - Act -
    results = await asyncio.gather(*(worker(i, r) for i, r in enumerate(instances)))

    # - Assert -
    assert sum(results) == 1
    assert len(entered) == 1


@pytest.mark.req("SYS-05-R20")
async def test_wait_acquires_after_release(redis_instances: Callable[[], Redis]) -> None:
    """С параметром `wait` второй инстанс дожидается освобождения и выполняет секцию последовательно."""
    # - Arrange -
    a, b = _instances(redis_instances, 2)
    order: list[str] = []

    async def holder() -> None:
        async with a.locks.acquire("seq", ttl=timedelta(seconds=5)):
            order.append("a-start")
            await asyncio.sleep(0.2)
            order.append("a-end")

    async def waiter() -> None:
        await asyncio.sleep(0.05)
        async with b.locks.acquire("seq", ttl=timedelta(seconds=5), wait=timedelta(seconds=2)):
            order.append("b")

    # - Act -
    await asyncio.gather(holder(), waiter())

    # - Assert -
    assert order == ["a-start", "a-end", "b"]


@pytest.mark.req("SYS-05-R15")
async def test_lock_fails_closed_without_redis(down_redis: ModuleRedis) -> None:
    """Без Redis блокировка не берётся (fail-closed): защищённая операция не выполняется."""
    with pytest.raises(RedisUnavailableError):
        async with down_redis.locks.acquire("job", ttl=timedelta(seconds=5)):
            pytest.fail("Секция не должна выполняться без Redis")
