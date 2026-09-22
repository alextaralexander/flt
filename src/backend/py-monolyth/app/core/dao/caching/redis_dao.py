"""DAO поверх Redis-клиента: JSON-значения, хеши, множества."""

import json
from collections.abc import Awaitable
from typing import Any, cast
from uuid import UUID

import redis.asyncio as redis


class RedisDAO:
    """Тонкая обёртка над redis.asyncio.Redis с сериализацией значений в JSON."""

    def __init__(self, redis_client: redis.Redis):
        """Принимает готовый (общий) клиент Redis."""
        self.redis = redis_client

    async def save(self, key: str, value: dict[str, Any], expire: int = 3600) -> None:
        """Сохранить данные в Redis."""
        await self.redis.setex(key, expire, json.dumps(value))

    async def update(self, key: str, value: dict[str, Any], expire: int = 3600) -> dict[str, Any] | None:
        """Обновить данные в Redis."""
        await self.save(key, value, expire)
        return await self.get(key)

    async def get(self, key: str) -> dict[str, Any] | None:
        """Получить данные из Redis."""
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def delete(self, key: str) -> None:
        """Удалить данные из Redis."""
        await self.redis.delete(key)

    async def get_set_members(self, key: str) -> list[str]:
        """Получить элементы множества из Redis."""
        # cast: redis-py аннотирует команды объединением sync/async интерфейсов.
        members = await cast("Awaitable[set[Any]]", self.redis.smembers(key))
        return [member.decode("utf-8") if isinstance(member, bytes) else member for member in members]

    async def get_hash_all(self, key: str) -> dict[str, str]:
        """Получить все поля и значения хеша из Redis."""
        result = await cast("Awaitable[dict[Any, Any]]", self.redis.hgetall(key))
        return {
            k.decode("utf-8") if isinstance(k, bytes) else k: v.decode("utf-8") if isinstance(v, bytes) else v
            for k, v in result.items()
        }

    @staticmethod
    def get_key(namespace: str, key: str | UUID) -> str:
        """Сформировать ключ с учётом namespace."""
        return f"{namespace}:{key}"
