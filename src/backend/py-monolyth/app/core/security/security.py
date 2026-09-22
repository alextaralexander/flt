"""Аутентификация и авторизация.

HTTP-цепочка: `Security(auth_user([...]))` → `get_current_user` (Bearer-токен →
пользователь) → `check_permissions`. В тестах переопределяется одна точка —
`get_current_user` через `app.dependency_overrides`.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import InsufficientPermissionsError, InvalidTokenError
from app.core.security.auth_service import get_auth_service
from app.core.security.schemas import UserSecuritySchema


oauth2_scheme = HTTPBearer(description="JWT access token (Bearer).")


async def check_token(token: str) -> UserSecuritySchema:
    """Проверяет JWT локально (ключ из настроек) и собирает пользователя с permissions."""
    auth_service = get_auth_service()
    decoded_token = auth_service.verify_token(token)

    user_id = auth_service.get_user_id(decoded_token)
    if not user_id:
        raise InvalidTokenError(token)
    permissions = auth_service.get_permissions(decoded_token)
    return UserSecuritySchema(user_id=user_id, permissions=permissions, access_token=token)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(oauth2_scheme)],
) -> UserSecuritySchema:
    """FastAPI-зависимость: пользователь из Bearer-токена.

    Единая точка аутентификации HTTP-слоя — именно её переопределяют тесты.
    """
    return await check_token(credentials.credentials)


def check_permissions(user: UserSecuritySchema, permissions_to_check: list[str]) -> None:
    """Проверяет, что у пользователя есть все требуемые permissions.

    Raises:
        InsufficientPermissionsError: не хватает хотя бы одного permission.
    """
    if not set(permissions_to_check).issubset(user.permissions):
        raise InsufficientPermissionsError(user=user, permissions_to_check=permissions_to_check)


def auth_user(
    permissions_to_check: list[str] | None = None,
) -> Callable[[UserSecuritySchema], Awaitable[UserSecuritySchema]]:
    """Фабрика HTTP-зависимости: аутентификация + проверка permissions.

    Действия:
    - `get_current_user` аутентифицирует пользователя по Bearer-токену;
    - `check_permissions` проверяет права, если передан `permissions_to_check`.
    """

    async def auth_user_and_check_permissions(
        user: Annotated[UserSecuritySchema, Depends(get_current_user)],
    ) -> UserSecuritySchema:
        """Проверка permissions аутентифицированного пользователя."""
        check_permissions(user, permissions_to_check or [])
        return user

    return auth_user_and_check_permissions
