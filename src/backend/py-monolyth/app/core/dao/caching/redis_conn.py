"""Общий Redis-клиент приложения.

Клиент создаётся лениво и переиспользуется всеми потребителями
(кэш-сервисы): у redis-py собственный пул соединений, поэтому один клиент
на процесс — норма. Закрывает его `lifespan` через `close_redis_client()`.

Клиент привязан к event loop-у: соединения нельзя переносить между loop-ами
(актуально для тестов, где каждый сценарий может получить свой loop).
"""

import asyncio

import redis

from app.core.dao.caching.redis_dao import RedisDAO
from app.core.logging.context import app_logger
from configs.redis_config import redis_settings


_redis_client: redis.asyncio.Redis | None = None
_redis_client_loop: asyncio.AbstractEventLoop | None = None


async def get_redis_client() -> redis.asyncio.Redis:
    """Общий клиент Redis (создаётся и проверяется ping-ом при первом обращении)."""
    global _redis_client, _redis_client_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_client_loop is not loop:
        client = redis.asyncio.Redis(
            host=redis_settings.REDIS_HOST,
            port=redis_settings.REDIS_PORT,
            db=redis_settings.REDIS_DB,
            decode_responses=redis_settings.REDIS_DECODE_RESPONSES,
            username=redis_settings.REDIS_USERNAME or None,
            password=redis_settings.REDIS_PASSWORD or None,
        )
        try:
            await client.ping()
        except Exception:
            app_logger.exception("Ошибка подключения к Redis")
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


async def get_redis_dao() -> RedisDAO:
    """DAO поверх общего клиента Redis."""
    return RedisDAO(await get_redis_client())
