"""Fixture Redis тестов shared kernel: `ModuleRedis` на отдельных клиентах и при недоступном Redis."""

from collections.abc import Callable

import pytest
from redis.asyncio import Redis

from app.core.dao.caching import ModuleRedis
from tests.support.redis_instances import TEST_PREFIX, redis_instances  # noqa: F401


@pytest.fixture
def module_redis(redis_instances: Callable[[], Redis]) -> ModuleRedis:  # noqa: F811
    """`ModuleRedis` с префиксом `shared_kernel` поверх отдельного клиента тестовой базы."""
    return ModuleRedis(TEST_PREFIX, client=redis_instances())


@pytest.fixture
def down_redis(redis_down: None) -> ModuleRedis:
    """`ModuleRedis` на общем клиенте процесса, направленном фикстурой `redis_down` на закрытый порт."""
    return ModuleRedis(TEST_PREFIX)
