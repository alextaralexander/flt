"""Аутентификация и авторизация HTTP-слоя.

HTTP-цепочка: `Security(auth_user([...]))` → `get_current_user` (Bearer-токен →
пользователь) → `check_permissions`. В тестах переопределяется одна точка —
`get_current_user` через `app.dependency_overrides`.

Проверка токена — `TokenVerifier` shared kernel (EdDSA по `kid` из `JWT_PUBLIC_KEYS`,
cookie и Bearer, отзыв сессий в Redis — ADR-006) появляется на этапе 1 Г.4. До этого
`check_token` отклоняет любой токен (fail-closed): симметричный ключ boilerplate
`JWT_SECRET_KEY` удалён (ADR-013), а защищённых эндпоинтов на этапе 1 Г.1 нет.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import InsufficientPermissionsError, InvalidTokenError
from app.core.logging.context import app_logger
from app.core.security.schemas import UserSecuritySchema


oauth2_scheme = HTTPBearer(description="JWT access token (Bearer).")


async def check_token(token: str) -> UserSecuritySchema:
    """Проверяет access-токен и собирает пользователя с правами.

    До `TokenVerifier` (этап 1 Г.4, ADR-006) ключей проверки нет, поэтому любой токен
    отклоняется — запрос получает 401, а не доступ без проверки.

    Raises:
        InvalidTokenError: всегда, пока проверка токенов не реализована.
    """
    app_logger.warning("Проверка access-токенов не настроена (TokenVerifier — этап 1 Г.4): запрос отклонён.")
    raise InvalidTokenError(token)


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
