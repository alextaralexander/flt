from typing import Dict

from fastapi import HTTPException
from redis.asyncio.client import StrictRedis

from py_main_lib.dao.redis_dao import RedisBaseDAO
from py_main_lib.security.schemas import TokenSettingsRedisSchema


class AuthDAO(RedisBaseDAO):
    def __init__(self, stand_name: str) -> None:
        self.stand_name: str = stand_name

    def _get_redis_prefix(self, key: str) -> str:
        """Генерация ключа Redis с префиксом стенда."""
        return f"{self.stand_name}.{key}"

    async def get_token_settings(self, redis_conn: StrictRedis) -> TokenSettingsRedisSchema:
        """Получить значения token_settings из Redis."""
        token_settings_key = self._get_redis_prefix("token_settings:token_settings")
        result = await self.get_hash_all(token_settings_key, redis_conn)

        if not result:
            raise ValueError(f"Хеш {token_settings_key} не найден.")

        token_settings = TokenSettingsRedisSchema(**result)

        if not token_settings.signKey:
            raise ValueError("Поле `signKey` не найдено в хеше {token_settings_key}.")

        return token_settings

    async def get_user_data(self, user_id: str, redis_conn: StrictRedis) -> Dict[str, str]:
        """Получение пользователя из Redis."""
        user_key = self._get_redis_prefix(f"user_info:{user_id}")
        user_data = await self.get_hash_all(user_key, redis_conn)

        if not user_data:
            user_ids = await self.get_set_members(self._get_redis_prefix("user_info"), redis_conn)
            if user_id not in user_ids:
                raise HTTPException(status_code=401, detail="User Not Found.")
        return user_data

    async def get_role_data(self, role_id: str, redis_conn: StrictRedis) -> Dict[str, str]:
        """Получение role из Redis."""
        role_key = self._get_redis_prefix(f"role_info:{role_id}")
        role_data = await self.get_hash_all(role_key, redis_conn)
        return role_data
