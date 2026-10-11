"""Общий Redis-клиент процесса (standalone или Sentinel — ADR-003, правило 9).

Клиент создаётся лениво и переиспользуется всеми потребителями: у redis-py
собственный пул соединений, поэтому один клиент на процесс — норма. Закрывает
его `lifespan` через `close_redis_client()`. Модули к клиенту напрямую не
обращаются: только обёртка `ModuleRedis` с префиксом модуля и обязательным TTL
(`app/core/dao/caching/module_redis.py`, ADR-003). Код модулей от режима Redis не зависит.

Клиент привязан к event loop-у: соединения нельзя переносить между loop-ами
(актуально для тестов, где каждый сценарий может получить свой loop).
"""

import asyncio
from typing import cast

import redis.asyncio as redis

from app.core.logging.context import app_logger
from configs.redis_config import RedisMode, RedisSettings, redis_settings


_redis_client: redis.Redis | None = None
_redis_client_loop: asyncio.AbstractEventLoop | None = None

# Таймаут сокета Sentinel (ADR-003, правило 9).
SENTINEL_SOCKET_TIMEOUT_SECONDS = 0.5


def create_redis_client(config: RedisSettings) -> redis.Redis:
    """Создаёт клиент Redis по режиму из настроек (без подключения — оно ленивое).

    Args:
        config: Настройки Redis.

    Returns:
        Клиент standalone-инстанса или мастера, найденного через Sentinel.
    """
    password = config.REDIS_PASSWORD.get_secret_value() or None
    if config.REDIS_MODE is RedisMode.SENTINEL:
        # redis-py не аннотирует конструктор Sentinel и master_for.
        sentinel = redis.Sentinel(  # type: ignore[no-untyped-call]
            config.sentinel_hosts,
            socket_timeout=SENTINEL_SOCKET_TIMEOUT_SECONDS,
            sentinel_kwargs={"password": password},
            password=password,
            db=config.REDIS_DB,
            decode_responses=config.REDIS_DECODE_RESPONSES,
        )
        return cast("redis.Redis", sentinel.master_for(config.REDIS_SENTINEL_MASTER))
    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        decode_responses=config.REDIS_DECODE_RESPONSES,
        password=password,
    )


async def get_redis_client() -> redis.Redis:
    """Общий клиент Redis (создаётся и проверяется ping-ом при первом обращении в текущем loop)."""
    global _redis_client, _redis_client_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_client_loop is not loop:
        client = create_redis_client(redis_settings)
        try:
            await client.ping()
        except Exception:
            app_logger.exception("Ошибка подключения к Redis")
            await client.aclose()
            raise
        _redis_client = client
        _redis_client_loop = loop
    return _redis_client


async def close_redis_client() -> None:
    """Закрыть общий Redis-клиент (вызывается из lifespan при shutdown)."""
    global _redis_client, _redis_client_loop
    if _redis_client is not None and _redis_client_loop is asyncio.get_running_loop():
        await _redis_client.aclose()
    _redis_client = None
    _redis_client_loop = None
