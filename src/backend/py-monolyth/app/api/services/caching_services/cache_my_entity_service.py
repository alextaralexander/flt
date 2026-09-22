"""Пример реализации сервиса для кэширования."""

from uuid import UUID

import redis.asyncio as redis
from fastapi import Depends

from app.api.schemas.caching_schemas.cache_entity_schema import (
    CacheMyEntitySchema,
    CreateCacheMyEntitySchema,
    UpdateCacheMyEntitySchema,
)
from app.core.dao.caching.redis_conn import get_redis_client
from app.core.dao.caching.redis_dao import RedisDAO


class CacheMyEntityService:
    """Пример сервиса, хранящего сущность в Redis вместо БД."""

    entity_name = "my_entity"

    def __init__(self, redis_client: redis.Redis = Depends(get_redis_client)):
        """Получает общий Redis-клиент через DI и оборачивает его в DAO."""
        self.dao = RedisDAO(redis_client)

    async def get_cached_data(self, entity_id: UUID | str) -> CacheMyEntitySchema | None:
        """Получить данные для сущности."""
        key = self.dao.get_key(self.entity_name, entity_id)
        value = await self.dao.get(key)
        return CacheMyEntitySchema(**value) if value else None

    async def save_data(self, entity: CreateCacheMyEntitySchema) -> CacheMyEntitySchema:
        """Сохранить данные для сущности."""
        key = self.dao.get_key(self.entity_name, entity.id)
        serialized_value = entity.model_dump()
        await self.dao.save(key, serialized_value)
        return CacheMyEntitySchema(**serialized_value)

    async def update_data(self, entity: UpdateCacheMyEntitySchema) -> CacheMyEntitySchema | None:
        """Обновить данные для сущности."""
        key = self.dao.get_key(self.entity_name, entity.id)
        serialized_value = entity.model_dump()
        value = await self.dao.update(key, serialized_value)
        return CacheMyEntitySchema(**value) if value else None

    async def delete_data(self, entity_id: UUID | str) -> None:
        """Удалить данные для сущности."""
        key = self.dao.get_key(self.entity_name, entity_id)
        await self.dao.delete(key)
