"""Аутентификация и авторизация HTTP и WebSocket (ADR-006, раздел 3.4; SYS-03-R21; SYS-04-R2; SYS-06-R5).

Цепочка HTTP: `Security(auth_user("<module>:<resource>:<action>"))` → `get_current_user` →
`get_optional_user` (токен → `TokenVerifier` → гранты от `RolePermissionsProvider`) → проверка права.
В тестах переопределяется одна точка — `get_current_user` (или `get_optional_user` для роутов с
анонимом) через `app.dependency_overrides`.

Порядок извлечения токена (ADR-006, раздел 3.4):

1. `Authorization: Bearer <jwt>` — cookie игнорируются, CSRF не проверяется;
2. cookie `__Host-flt_access` — для `POST`, `PUT`, `PATCH`, `DELETE` обязателен `X-CSRF-Token`,
   равный cookie `__Host-flt_csrf` и подписанный для сессии токена (иначе `403 identity.csrf_invalid`);
3. иначе — аноним: `401 core.unauthenticated` для защищённых роутов.

Токен в query-string не читается никогда. Объявление доступа роута (`auth_user`, `auth_user_optional`,
`public()`) читается из его зависимостей функцией `access_declaration` — так архитектурный тест
проверяет, что каждый роут объявляет доступ (SYS-06-R5).
"""

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, Request, Security, WebSocket, params
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocketDisconnect
from structlog.contextvars import bind_contextvars

from app.core.container import container
from app.core.security.csrf import CSRF_COOKIE, CSRF_HEADER, UNSAFE_METHODS, csrf_token_valid
from app.core.security.errors import CsrfInvalidError, ForbiddenError, UnauthenticatedError
from app.core.security.permissions import (
    DenyAllPermissionsProvider,
    Grant,
    RolePermissionsProvider,
    UserFlags,
    validate_permission_code,
)
from app.core.security.schemas import UserSecuritySchema
from app.core.security.tokens import TokenVerifier
from configs.settings import settings


ACCESS_COOKIE = "__Host-flt_access"
WS_UNAUTHENTICATED_CODE = 4401
WS_UNAUTHENTICATED_REASON = "unauthenticated"
ACCESS_ATTRIBUTE = "__flt_access__"

# Схемы безопасности OpenAPI — имена из Analytics/Specs/_system/openapi-common.yaml.
bearer_scheme = HTTPBearer(scheme_name="bearerAuth", auto_error=False, description="Access JWT EdDSA (Bearer).")
cookie_scheme = APIKeyCookie(
    name=ACCESS_COOKIE,
    scheme_name="cookieAuth",
    auto_error=False,
    description="Access JWT в httpOnly-cookie; изменяющие методы требуют X-CSRF-Token.",
)


@dataclass(frozen=True)
class AccessDeclaration:
    """Объявленный доступ роута или обработчика (SYS-06-R5).

    Attributes:
        kind: `user` — `auth_user`, `optional` — `auth_user_optional`, `public` — `public()`,
            `websocket` — `auth_websocket` (право канала проверяет обработчик модуля).
        permission: Код права или None.
    """

    kind: Literal["user", "optional", "public", "websocket"]
    permission: str | None = None


def access_declaration(call: object) -> AccessDeclaration | None:
    """Объявление доступа, которое несёт зависимость (`auth_user(...)` и т.п.), или None."""
    declaration = getattr(call, ACCESS_ATTRIBUTE, None)
    return declaration if isinstance(declaration, AccessDeclaration) else None


def _declare[F](dependency: F, declaration: AccessDeclaration) -> F:
    """Помечает зависимость объявлением доступа."""
    setattr(dependency, ACCESS_ATTRIBUTE, declaration)
    return dependency


def get_token_verifier() -> TokenVerifier:
    """Верификатор процесса из контейнера; без регистрации — из настроек (ключи неизменны в процессе)."""
    return container.resolve_optional(TokenVerifier) or TokenVerifier.from_settings()


def get_role_permissions_provider() -> RolePermissionsProvider:
    """Провайдер ролей, зарегистрированный модулем `identity`, или запрет всего (fail-closed)."""
    return container.resolve_optional(RolePermissionsProvider) or DenyAllPermissionsProvider()


def _bearer_token(conn: HTTPConnection) -> str | None:
    """Токен из `Authorization: Bearer`; заголовок другой схемы или пустой — 401."""
    header = conn.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise UnauthenticatedError("invalid_token")
    return token


def _check_csrf(conn: HTTPConnection, user: UserSecuritySchema) -> None:
    """Signed double-submit: заголовок равен cookie и подписан для сессии токена (ADR-006, раздел 3.4)."""
    header = conn.headers.get(CSRF_HEADER)
    cookie = conn.cookies.get(CSRF_COOKIE)
    if not header or not cookie or not hmac.compare_digest(header.encode(), cookie.encode()):
        raise CsrfInvalidError()
    if not csrf_token_valid(header, user.sid, settings.AUTH_CSRF_SECRET.get_secret_value()):
        raise CsrfInvalidError()


def _origin_allowed(conn: HTTPConnection) -> bool:
    """`Origin` совпадает с `APP_PUBLIC_URL` (схема, хост, порт) — для cookie-клиентов WebSocket."""
    origin = conn.headers.get("origin")
    if not origin:
        return False
    expected = urlsplit(settings.APP_PUBLIC_URL)
    actual = urlsplit(origin)
    return (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc)


async def with_grants(user: UserSecuritySchema) -> UserSecuritySchema:
    """Пользователь с грантами, выведенными провайдером ролей для этого запроса (SYS-06-R4)."""
    grants = await get_role_permissions_provider().grants_for(user.roles, user.flags)
    return user.model_copy(update={"permissions": frozenset(grant.bind(user.user_id) for grant in grants)})


async def authenticate(conn: HTTPConnection, *, websocket: bool = False) -> UserSecuritySchema | None:
    """Аутентифицирует запрос или handshake: Bearer, иначе cookie; без учётных данных — None.

    Args:
        conn: HTTP-запрос или WebSocket.
        websocket: Handshake WebSocket: для cookie проверяется `Origin` вместо CSRF.

    Returns:
        Пользователь с грантами запроса или None (аноним).

    Raises:
        UnauthenticatedError: Токен невалиден, отозван, это токен агента или `Origin` не совпал.
        CsrfInvalidError: Cookie-клиент вызвал изменяющий метод без валидного CSRF-токена.
    """
    token = _bearer_token(conn)
    from_cookie = False
    if token is None:
        token = conn.cookies.get(ACCESS_COOKIE)
        from_cookie = token is not None
    if not token:
        return None

    user = await get_token_verifier().verify(token)
    if from_cookie and websocket and not _origin_allowed(conn):
        raise UnauthenticatedError("origin_mismatch")
    if from_cookie and not websocket and conn.scope.get("method", "GET").upper() in UNSAFE_METHODS:
        _check_csrf(conn, user)
    bind_contextvars(user_id=str(user.user_id))
    return await with_grants(user)


async def get_optional_user(
    request: Request,
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    _cookie: Annotated[str | None, Security(cookie_scheme)],
) -> UserSecuritySchema | None:
    """FastAPI-зависимость: пользователь запроса с грантами или None для анонима.

    Параметры схем безопасности нужны только для OpenAPI (`bearerAuth`, `cookieAuth`);
    сами учётные данные читает `authenticate`.
    """
    return await authenticate(request)


async def get_current_user(
    user: Annotated[UserSecuritySchema | None, Depends(get_optional_user)],
) -> UserSecuritySchema:
    """FastAPI-зависимость: аутентифицированный пользователь с грантами; аноним — 401.

    Единая точка аутентификации HTTP-слоя — именно её переопределяют тесты.
    """
    if user is None:
        raise UnauthenticatedError("missing_token")
    return user


async def check_permission(user: UserSecuritySchema, permission: str) -> Grant:
    """Грант права `permission` пользователя; нет права — 403 с кодом провайдера или `core.forbidden`.

    Raises:
        ForbiddenError: Права нет; код уточняет `RolePermissionsProvider.denial_code` (SYS-06-R7).
    """
    grant = user.grant(permission)
    if grant is not None:
        return grant
    code = await get_role_permissions_provider().denial_code(permission, user.roles, user.flags)
    raise ForbiddenError(code) if code else ForbiddenError()


def auth_user(permission: str) -> Callable[..., Awaitable[UserSecuritySchema]]:
    """Фабрика зависимости роута: аутентификация и проверка права (SYS-06-R5).

    Args:
        permission: Код права `<module>:<resource>:<action>` из матрицы SYS-06.

    Returns:
        Зависимость, возвращающая пользователя; его грант права — `user.grant(permission)`.

    Raises:
        ValueError: Код права не по формату SYS-06-R2 (при объявлении роута).
    """
    validate_permission_code(permission)

    async def auth_user_and_check_permission(
        user: Annotated[UserSecuritySchema, Depends(get_current_user)],
    ) -> UserSecuritySchema:
        """Проверка права аутентифицированного пользователя."""
        await check_permission(user, permission)
        return user

    return _declare(auth_user_and_check_permission, AccessDeclaration("user", permission))


def auth_user_optional(permission: str) -> Callable[..., Awaitable[UserSecuritySchema | None]]:
    """Фабрика зависимости роута, допускающего анонима с правом из столбца «аноним» (SYS-06-R5, R10).

    Аноним проходит, если провайдер ролей выдаёт право анониму (иначе 401); аутентифицированный
    пользователь проверяется как в `auth_user` (иначе 403).

    Args:
        permission: Код права `<module>:<resource>:<action>`.

    Returns:
        Зависимость, возвращающая пользователя или None для анонима.
    """
    validate_permission_code(permission)

    async def auth_optional_and_check_permission(
        user: Annotated[UserSecuritySchema | None, Depends(get_optional_user)],
    ) -> UserSecuritySchema | None:
        """Проверка права пользователя или анонима."""
        if user is not None:
            await check_permission(user, permission)
            return user
        anonymous = await get_role_permissions_provider().grants_for((), UserFlags.anonymous())
        if not any(grant.code == permission for grant in anonymous):
            raise UnauthenticatedError("missing_token")
        return None

    return _declare(auth_optional_and_check_permission, AccessDeclaration("optional", permission))


def public() -> params.Depends:
    """Маркер `public=True` анонимного роута: `@router.get(..., dependencies=[public()])` (SYS-06-R5, R10).

    Допустим только для прав, у которых в столбце «аноним» матрицы SYS-06 стоит `✓`.
    """

    async def public_access() -> None:
        """Роут доступен без аутентификации."""

    return params.Depends(_declare(public_access, AccessDeclaration("public")))


def auth_websocket() -> Callable[[WebSocket], Awaitable[UserSecuritySchema]]:
    """Фабрика зависимости WebSocket: аутентификация при handshake (SYS-04-R2; ADR-006, раздел 3.7).

    Bearer или cookie `__Host-flt_access` с `Origin`, равным `APP_PUBLIC_URL`. При неуспехе соединение
    принимается и сразу закрывается кодом `4401` с причиной `unauthenticated` без сообщений —
    браузерный клиент получает код и выполняет refresh. Идентичность и гранты фиксируются на всё
    время соединения; права каналов проверяет обработчик модуля.
    """

    async def authenticate_websocket(websocket: WebSocket) -> UserSecuritySchema:
        """Пользователь handshake или закрытие 4401."""
        try:
            user = await authenticate(websocket, websocket=True)
        except UnauthenticatedError:
            user = None
        if user is None:
            await websocket.accept()
            await websocket.close(code=WS_UNAUTHENTICATED_CODE, reason=WS_UNAUTHENTICATED_REASON)
            raise WebSocketDisconnect(code=WS_UNAUTHENTICATED_CODE, reason=WS_UNAUTHENTICATED_REASON)
        return user

    return _declare(authenticate_websocket, AccessDeclaration("websocket"))
