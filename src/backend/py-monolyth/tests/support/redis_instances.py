"""Независимые клиенты тестовой базы Redis — имитация инстансов монолита (SYS-05-R51; ADR-003).

Каждый клиент — свой пул соединений, как у отдельного процесса роли `api` или `worker`:
тесты shared kernel проверяют, что блокировки, лимиты, идемпотентность и предохранитель
действуют глобально, а не на каждом «инстансе» отдельно. Ключи тестов — с префиксом
`shared_kernel`, чтобы их принимала фикстура `redis_no_persistent_keys` при пустом реестре модулей.
"""

from collections.abc import AsyncIterator, Callable

import pytest_asyncio
from redis.asyncio import Redis

from app.core.dao.caching.redis_conn import create_redis_client
from configs.redis_config import redis_settings


TEST_PREFIX = "shared_kernel"


@pytest_asyncio.fixture
async def redis_instances() -> AsyncIterator[Callable[[], Redis]]:
    """Фабрика независимых клиентов Redis; все клиенты закрываются после теста."""
    clients: list[Redis] = []

    def factory() -> Redis:
        client = create_redis_client(redis_settings)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()
