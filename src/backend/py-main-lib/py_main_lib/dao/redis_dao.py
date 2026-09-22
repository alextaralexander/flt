"""Repository for work with redis."""

import json
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from redis.asyncio.client import Pipeline, StrictRedis


class RedisBaseDAO:
    """Repo для взаимодействия с Redis."""

    @classmethod
    async def get_data(cls, key: str, redis_conn: StrictRedis) -> Optional[Any]:
        """Получает данные из Redis по ключу."""
        data = await redis_conn.get(key)
        return json.loads(str(data)) if data is not None else None

    @classmethod
    async def set_data_permanently(cls, key: str, value: Any, redis_conn: StrictRedis) -> bool:
        """Сохраняет данные в Redis."""
        serialized_value = json.dumps(value, ensure_ascii=False)
        await redis_conn.set(name=key, value=serialized_value)
        return True

    @classmethod
    async def get_set_members(cls, key: str, redis_conn: StrictRedis) -> List[str]:
        """Получить элементы множества из Redis."""
        return [
            member.decode("utf-8") if isinstance(member, bytes) else member for member in await redis_conn.smembers(key)
        ]

    @classmethod
    async def get_hash_all(cls, key: str, redis_conn: StrictRedis) -> Dict[str, str]:
        """Получить все поля и значения хеша из Redis."""
        result = await redis_conn.hgetall(key)
        return {
            k.decode("utf-8") if isinstance(k, bytes) else k: v.decode("utf-8") if isinstance(v, bytes) else v
            for k, v in result.items()
        }

    @classmethod
    async def set_data(cls, key: str, value: Any, pipeline: Pipeline, expire: Optional[int] = None) -> bool:
        """Сохраняет данные в Redis."""
        serialized_value = json.dumps(value, ensure_ascii=False)
        await pipeline.set(name=key, value=serialized_value, ex=expire)
        return True

    @classmethod
    async def delete_data(cls, key: str, pipeline: Pipeline) -> bool:
        """Удаляет данные из Redis по ключу."""
        await pipeline.delete(key)
        return True

    @staticmethod
    def generate_key(model_name: str, model_id: Union[str, UUID]) -> str:
        """Генерирует ключ для хранения данных в Redis."""
        return f"{model_name}:{model_id}"
