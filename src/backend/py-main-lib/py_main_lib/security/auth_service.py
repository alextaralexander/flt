from typing import Any, Dict, List, Set, cast

import jwt
from redis.asyncio import StrictRedis

from py_main_lib.exceptions import InvalidTokenError
from py_main_lib.security.auth_dao import AuthDAO


class AuthService:
    def __init__(self, auth_dao: AuthDAO, redis_conn: StrictRedis):
        self.auth_dao: AuthDAO = auth_dao
        self.redis_conn = redis_conn
        self.token_sign_key: str | None = None

    async def initialize(self) -> None:
        """Инициализация сервиса: загрузка ключа подписи токена в память."""
        await self.get_token_sign_key()

    async def get_token_sign_key(self) -> str:
        """Получение ключа подписи токена из Redis."""
        if self.token_sign_key is not None:
            return self.token_sign_key

        token_settings = await self.auth_dao.get_token_settings(self.redis_conn)
        self.token_sign_key = token_settings.signKey
        return self.token_sign_key

    async def get_user_role_ids(self, user_id: str) -> List[str]:
        """Получение ID ролей пользователя из Redis."""
        user_data = await self.auth_dao.get_user_data(user_id, self.redis_conn)

        # Извлекаем ID ролей пользователя
        role_ids = []
        for key, value in user_data.items():
            if key.startswith("roleNames"):
                role_ids.append(value)

        return role_ids

    async def get_user_permissions(self, user_id: str) -> Set[str]:
        """Получение дополнительных permissions пользователя из Redis"""
        user_data = await self.auth_dao.get_user_data(user_id, self.redis_conn)

        # Извлекаем permissions пользователя
        permissions = set()
        for key, value in user_data.items():
            if key.startswith("permissions."):
                permissions.add(value)

        return permissions

    async def get_role_permissions(self, role_id: str) -> Set[str]:
        """Получение Permissions роли из Redis"""
        role_data = await self.auth_dao.get_role_data(role_id, self.redis_conn)

        # Извлекаем Permissions из полей роли
        permissions = set()
        for key, value in role_data.items():
            if key.startswith("permissions."):
                permissions.add(value)

        return permissions

    async def get_all_user_permissions(self, user_id: str) -> Set[str]:
        """Получение всех permissions пользователя (дополнительные + из ролей)"""
        user_permissions = await self.get_user_permissions(user_id)
        role_ids = await self.get_user_role_ids(user_id)

        # Получаем permissions из всех ролей
        all_permissions = user_permissions.copy()
        for role_id in role_ids:
            role_permissions = await self.get_role_permissions(role_id)
            all_permissions.update(role_permissions)

        return all_permissions

    async def verify_token(self, token: str) -> Dict[str, Any]:
        """Проверка JWT токена и извлечение данных"""
        sign_key = await self.get_token_sign_key()
        try:
            decoded_token = jwt.decode(token, sign_key, algorithms=["HS256"])
        except Exception:
            raise InvalidTokenError(token)
        return cast(Dict[str, Any], decoded_token)


async def get_auth_service(
    stand_name: str,
    redis_conn: StrictRedis,
) -> AuthService:
    """Создание сервиса авторизации."""
    auth_dao = AuthDAO(stand_name)
    auth_service = AuthService(auth_dao, redis_conn)
    await auth_service.initialize()
    return auth_service
