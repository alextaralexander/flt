"""Аутентификация и авторизация shared kernel (ADR-006, SYS-06): публичный интерфейс для модулей.

- `auth_user(permission)`, `auth_user_optional(permission)`, `public()`, `auth_websocket()` —
  объявление доступа роутов и обработчиков WebSocket;
- `UserSecuritySchema`, `Grant`, `Permission`, `Scope` — пользователь запроса и его права;
- `TokenVerifier` — проверка access JWT; `RolePermissionsProvider` — интерфейс, который
  реализует модуль `identity`; `issue_csrf_token` — выпуск CSRF-токена для `identity`.
"""

from app.core.security.csrf import CSRF_COOKIE, CSRF_HEADER, csrf_token_valid, issue_csrf_token
from app.core.security.errors import CsrfInvalidError, ForbiddenError, UnauthenticatedError
from app.core.security.permissions import (
    PERMISSION_ACTIONS,
    DenyAllPermissionsProvider,
    Grant,
    Permission,
    RolePermissionsProvider,
    Scope,
    UserFlags,
    validate_permission_code,
)
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import (
    ACCESS_COOKIE,
    AccessDeclaration,
    access_declaration,
    auth_user,
    auth_user_optional,
    auth_websocket,
    check_permission,
    get_current_user,
    get_optional_user,
    public,
)
from app.core.security.tokens import RedisRevocationChecker, TokenVerifier, load_verification_keys


__all__ = (
    "ACCESS_COOKIE",
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "PERMISSION_ACTIONS",
    "AccessDeclaration",
    "CsrfInvalidError",
    "DenyAllPermissionsProvider",
    "ForbiddenError",
    "Grant",
    "Permission",
    "RedisRevocationChecker",
    "RolePermissionsProvider",
    "Scope",
    "TokenVerifier",
    "UnauthenticatedError",
    "UserFlags",
    "UserSecuritySchema",
    "access_declaration",
    "auth_user",
    "auth_user_optional",
    "auth_websocket",
    "check_permission",
    "csrf_token_valid",
    "get_current_user",
    "get_optional_user",
    "issue_csrf_token",
    "load_verification_keys",
    "public",
    "validate_permission_code",
)
