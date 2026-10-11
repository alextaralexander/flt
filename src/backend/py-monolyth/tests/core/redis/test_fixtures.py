"""Тесты фикстур Redis: очистка базы 15, контроль TTL и префиксов, `redis_down` (SYS-10-R6).

Тесты создают ключи сырым клиентом тестовой базы и удаляют нарушающие ключи в блоке `Clean`,
чтобы фикстура `redis_no_persistent_keys` после теста проверяла уже чистую базу.
"""

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.dao.caching.redis_conn import get_redis_client
from configs.redis_config import redis_settings
from tests.support.redis_keys import find_invalid_keys


pytestmark = pytest.mark.req("SYS-10-R6")

MODULES = ("identity",)


async def test_redis_db_is_empty_at_start(raw_test_redis: Redis) -> None:
    """`redis_clean` очищает базу 15 перед каждым тестом, тест работает только с ней."""
    # - Act -
    size = await raw_test_redis.dbsize()

    # - Assert -
    assert redis_settings.REDIS_DB == 15
    assert size == 0


@pytest.mark.req("SYS-05-R12")
async def test_key_without_ttl_is_reported_by_name(raw_test_redis: Redis) -> None:
    """Ключ без TTL (`TTL == -1`), созданный сырым клиентом, называется в отчёте фикстуры."""
    # - Arrange -
    await raw_test_redis.set("identity:session:probe", "1")

    # - Act -
    problems = await find_invalid_keys(raw_test_redis, MODULES)

    # - Clean -
    await raw_test_redis.delete("identity:session:probe")

    # - Assert -
    assert problems == ["identity:session:probe (ttl=-1: ключ без TTL (SYS-05-R12))"]


@pytest.mark.req("SYS-05-R11")
async def test_key_without_module_prefix_is_reported(raw_test_redis: Redis) -> None:
    """Ключ без префикса модуля реестра или `shared_kernel:` — нарушение."""
    # - Arrange -
    await raw_test_redis.set("orphan:key", "1", ex=60)
    await raw_test_redis.set("noprefix", "1", ex=60)

    # - Act -
    problems = await find_invalid_keys(raw_test_redis, MODULES)

    # - Clean -
    await raw_test_redis.delete("orphan:key", "noprefix")

    # - Assert -
    assert [problem.split(" ")[0] for problem in problems] == ["noprefix", "orphan:key"]


@pytest.mark.req("SYS-05-R13")
async def test_ttl_above_category_maximum_is_reported(raw_test_redis: Redis) -> None:
    """TTL сверх 24 ч и блокировка дольше 60 с — нарушения; блокировка планировщика — до 24 ч."""
    # - Arrange -
    await raw_test_redis.set("identity:cache:probe", "1", ex=25 * 3600)
    await raw_test_redis.set("identity:lock:probe", "1", ex=120)
    await raw_test_redis.set("shared_kernel:lock:schedule:identity.purge", "1", ex=3600)

    # - Act -
    problems = await find_invalid_keys(raw_test_redis, MODULES)

    # - Clean -
    await raw_test_redis.delete("identity:cache:probe", "identity:lock:probe")

    # - Assert -
    assert [problem.split(" ")[0] for problem in problems] == ["identity:cache:probe", "identity:lock:probe"]


async def test_keys_with_prefix_and_ttl_pass(raw_test_redis: Redis) -> None:
    """Ключи с префиксом и TTL в пределах категории нарушений не дают."""
    # - Arrange -
    await raw_test_redis.set("identity:session:ok", "1", ex=600)
    await raw_test_redis.set("shared_kernel:lock:outbox:identity", "1", ex=30)

    # - Act -
    problems = await find_invalid_keys(raw_test_redis, MODULES)

    # - Clean - (модуля identity в реестре ещё нет — фикстура после теста сочла бы ключ чужим)
    await raw_test_redis.delete("identity:session:ok")

    # - Assert -
    assert problems == []


@pytest.mark.req("SYS-05-R15")
@pytest.mark.usefixtures("redis_down")
async def test_redis_down_gives_connection_error() -> None:
    """`redis_down` направляет Redis-клиент процесса на закрытый порт: обращение — `ConnectionError`."""
    # - Act / Assert -
    with pytest.raises(RedisConnectionError):
        await get_redis_client()
