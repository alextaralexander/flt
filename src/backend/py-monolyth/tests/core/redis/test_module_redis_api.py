"""Тесты обёртки `ModuleRedis`: префикс модуля, обязательный TTL, доступ к Redis (ADR-003, SYS-05)."""

import inspect
from collections.abc import Callable
from datetime import timedelta

import pytest
from redis.asyncio import Redis

from app.core.dao.caching import ModuleRedis, RedisUnavailableError


# Публичные методы, которые создают или продлевают ключ, обязаны принимать `ttl` (SYS-05-R12).
WRITE_METHODS = ("set", "set_json", "incr", "hset", "sadd", "zadd", "expire")
FORBIDDEN_METHODS = ("persist", "keys", "flushdb", "flushall", "scan", "scan_iter")


@pytest.mark.req("SYS-05-R12")
def test_every_write_method_requires_ttl() -> None:
    """Каждый метод записи требует keyword-only `ttl` без значения по умолчанию; методов без TTL нет."""
    # - Act / Assert -
    for name in WRITE_METHODS:
        parameter = inspect.signature(getattr(ModuleRedis, name)).parameters["ttl"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name
        assert parameter.annotation in (timedelta, "timedelta"), name
    for name in FORBIDDEN_METHODS:
        assert not hasattr(ModuleRedis, name), name


@pytest.mark.req("SYS-05-R11")
@pytest.mark.parametrize("prefix", ["", "Identity", "core-test", "core:test", "1core"])
def test_prefix_must_be_module_name(prefix: str) -> None:
    """Префикс — имя модуля в snake_case; иное значение отклоняется."""
    with pytest.raises(ValueError, match="prefix"):
        ModuleRedis(prefix)


@pytest.mark.req("SYS-05-R11")
@pytest.mark.req("SYS-05-R12")
async def test_set_get_adds_prefix_and_ttl(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """`set` пишет ключ `<module>:<key>` с TTL, `get` читает его по ключу без префикса."""
    # - Act -
    await module_redis.set("entity:1", "value", ttl=timedelta(seconds=30))

    # - Assert -
    assert await module_redis.get("entity:1") == "value"
    assert await raw_test_redis.get("shared_kernel:entity:1") == "value"
    assert 0 < await raw_test_redis.ttl("shared_kernel:entity:1") <= 30
    assert await module_redis.ttl("entity:1") is not None


@pytest.mark.req("SYS-05-R12")
async def test_set_nx_and_delete(module_redis: ModuleRedis) -> None:
    """`set(nx=True)` не перезаписывает существующий ключ; `delete` удаляет ключи и считает их."""
    # - Act -
    first = await module_redis.set("k", "a", ttl=timedelta(seconds=5), nx=True)
    second = await module_redis.set("k", "b", ttl=timedelta(seconds=5), nx=True)

    # - Assert -
    assert (first, second) == (True, False)
    assert await module_redis.get("k") == "a"
    assert await module_redis.exists("k") is True
    assert await module_redis.delete("k", "missing") == 1
    assert await module_redis.get("k") is None
    assert await module_redis.ttl("k") is None


@pytest.mark.req("SYS-05-R12")
async def test_json_values(module_redis: ModuleRedis) -> None:
    """`set_json`/`get_json` сохраняют JSON-значения с TTL."""
    # - Act -
    await module_redis.set_json("cache:1", {"a": [1, 2], "b": None}, ttl=timedelta(minutes=1))

    # - Assert -
    assert await module_redis.get_json("cache:1") == {"a": [1, 2], "b": None}
    assert await module_redis.get_json("cache:missing") is None


@pytest.mark.req("SYS-05-R12")
async def test_incr_sets_ttl_once(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """`incr` атомарно увеличивает счётчик и ставит TTL при создании ключа (окно не сдвигается)."""
    # - Act -
    first = await module_redis.incr("counter", ttl=timedelta(seconds=30))
    await raw_test_redis.pexpire("shared_kernel:counter", 10_000)
    second = await module_redis.incr("counter", ttl=timedelta(seconds=30), amount=5)

    # - Assert -
    assert (first, second) == (1, 6)
    assert 0 < await raw_test_redis.pttl("shared_kernel:counter") <= 10_000


@pytest.mark.req("SYS-05-R12")
async def test_hash_set_and_sorted_set(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """Хеши, множества и сортированные множества создаются только с TTL."""
    # - Act -
    await module_redis.hset("h", {"a": "1", "b": "2"}, ttl=timedelta(seconds=30))
    await module_redis.sadd("s", "x", "y", ttl=timedelta(seconds=30))
    await module_redis.zadd("z", {"m": 1.0}, ttl=timedelta(seconds=30))
    await module_redis.expire("h", ttl=timedelta(seconds=20))

    # - Assert -
    assert await module_redis.hgetall("h") == {"a": "1", "b": "2"}
    assert await module_redis.hget("h", "a") == "1"
    assert await module_redis.smembers("s") == {"x", "y"}
    assert await module_redis.srem("s", "x") == 1
    for key in ("shared_kernel:h", "shared_kernel:s", "shared_kernel:z"):
        assert await raw_test_redis.ttl(key) > 0
    assert await raw_test_redis.ttl("shared_kernel:h") <= 20


@pytest.mark.req("SYS-05-R13")
@pytest.mark.parametrize("ttl", [timedelta(hours=24, seconds=1), timedelta(0), timedelta(seconds=-1)])
async def test_ttl_above_24h_rejected(module_redis: ModuleRedis, ttl: timedelta) -> None:
    """TTL больше 24 часов, нулевой и отрицательный отклоняются до обращения к Redis."""
    with pytest.raises(ValueError, match="ttl"):
        await module_redis.set("k", "v", ttl=ttl)


@pytest.mark.req("SYS-05-R14")
async def test_scan_module_keys_forces_prefix(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """`scan_module_keys` видит только ключи своего модуля и возвращает их без префикса."""
    # - Arrange -
    await module_redis.set("a:1", "1", ttl=timedelta(seconds=30))
    await module_redis.set("a:2", "1", ttl=timedelta(seconds=30))
    await module_redis.set("b:1", "1", ttl=timedelta(seconds=30))
    await raw_test_redis.set("other_module:a:1", "1", ex=30)

    # - Act -
    keys = [key async for key in module_redis.scan_module_keys("a:*")]
    all_keys = [key async for key in module_redis.scan_module_keys()]

    # - Assert -
    assert sorted(keys) == ["a:1", "a:2"]
    assert sorted(all_keys) == ["a:1", "a:2", "b:1"]

    # - Clean - (ключ чужого префикса фикстура `redis_no_persistent_keys` сочла бы нарушением)
    await raw_test_redis.delete("other_module:a:1")


@pytest.mark.req("SYS-05-R24")
async def test_publish_uses_module_prefix(module_redis: ModuleRedis, redis_instances: Callable[[], Redis]) -> None:
    """`publish` отправляет сообщение в канал `<module>:<channel>`; подписчик на другом клиенте его получает."""
    # - Arrange -
    subscriber = redis_instances()
    pubsub = subscriber.pubsub()
    await pubsub.subscribe("shared_kernel:reply:1")

    # - Act -
    received = await module_redis.publish("reply:1", "hello")
    message = None
    for _ in range(50):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if message:
            break

    # - Assert -
    assert received == 1
    assert message is not None
    assert message["data"] == "hello"
    await pubsub.aclose()


@pytest.mark.req("SYS-05-R15")
async def test_unavailable_redis_raises_connection_error(down_redis: ModuleRedis) -> None:
    """Недоступный Redis — `RedisUnavailableError` (наследник `ConnectionError`), без «сырых» исключений redis."""
    with pytest.raises(RedisUnavailableError) as exc_info:
        await down_redis.get("k")
    assert isinstance(exc_info.value, ConnectionError)


@pytest.mark.req("SYS-05-R11")
async def test_default_client_is_shared_process_client(raw_test_redis: Redis) -> None:
    """Без явного клиента `ModuleRedis` использует общий клиент процесса `get_redis_client()`."""
    # - Act -
    redis = ModuleRedis("shared_kernel")
    await redis.set("default", "1", ttl=timedelta(seconds=5))

    # - Assert -
    assert await raw_test_redis.get("shared_kernel:default") == "1"
