from typing import Annotated, AsyncGenerator, Awaitable, Callable, List

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import StrictRedis

from py_main_lib.exceptions import InsufficientPermissionsError, InvalidTokenError
from py_main_lib.security.auth_service import get_auth_service
from py_main_lib.security.schemas import UserSecuritySchema


oauth2_scheme = HTTPBearer(description="Токен для авторизации в ms-auth.")


async def ms_auth_check_token(
    token: str,
    stand_name: str,
    redis_conn: StrictRedis,
) -> UserSecuritySchema:
    """Проверка токена в Redis."""
    auth_service = await get_auth_service(stand_name, redis_conn)
    decoded_token = await auth_service.verify_token(token)

    user_id = decoded_token.get("USER_ID")
    if not user_id:
        raise InvalidTokenError(token)
    all_permissions = await auth_service.get_all_user_permissions(user_id)
    user = UserSecuritySchema(user_id=user_id, permissions=all_permissions, access_token=token)
    return user


def check_permissions(user: UserSecuritySchema, permissions_to_check: List[str]) -> None:
    """Проверяет, содержит ли пользователь необходимые permissions."""
    if not set(permissions_to_check).issubset(user.permissions):
        raise InsufficientPermissionsError(user=user, permissions_to_check=permissions_to_check)


def auth_user(
    permissions_to_check: List[str] | None = None,
    stand_name: str | None = None,
    get_redis_conn: Callable[[], AsyncGenerator[StrictRedis, None]] | None = None,
) -> Callable[[HTTPAuthorizationCredentials, Request], Awaitable[UserSecuritySchema]]:
    """Аутентификация пользователя.

    Действия:
    - Берем токен из запроса к нашему сервису;
    - Проверяем и декодируем токен с использованием ключа из Redis;
    - Получаем permissions пользователя и его ролей из Redis;
    - Создаем схему аутентификационного пользователя;
    - Если передан параметр `permissions_to_check`, проверяет, есть ли у пользователя указанные разрешения.
    """

    resolved_stand_name = stand_name
    resolved_get_redis_conn = get_redis_conn
    if resolved_stand_name is None:
        raise ValueError("stand_name must be provided for auth_user")
    if resolved_get_redis_conn is None:
        raise ValueError("get_redis_conn must be provided for auth_user")

    async def auth_user_and_check_permissions(
        credentials: Annotated[HTTPAuthorizationCredentials, Security(oauth2_scheme)],
        request: Request,
    ) -> UserSecuritySchema:
        """Выполнение логики аутентификации и проверки разрешений."""
        token = credentials.credentials
        user: UserSecuritySchema | None = None
        async for redis_conn in resolved_get_redis_conn():
            user = await ms_auth_check_token(token, resolved_stand_name, redis_conn)
        if user is None:
            raise ValueError("get_redis_conn did not yield a Redis connection")

        if permissions_to_check and not set(permissions_to_check).issubset(user.permissions):
            raise InsufficientPermissionsError(user=user, permissions_to_check=permissions_to_check)

        request.state.user = user
        return user

    return auth_user_and_check_permissions
