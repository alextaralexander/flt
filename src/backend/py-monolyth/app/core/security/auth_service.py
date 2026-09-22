"""Сервис аутентификации: локальная верификация JWT и сборка permissions из claims.

Сервис самодостаточен: внешний сервис авторизации не нужен. Ключ проверки
подписи и маппинг ролей на permissions берутся из настроек
(`JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_ROLE_PERMISSIONS`).
"""

import time
from collections.abc import Iterable, Mapping
from typing import Any

import jwt

from app.core.exceptions import InvalidTokenError
from configs.settings import settings


USER_ID_CLAIM = "USER_ID"
PERMISSIONS_CLAIM = "PERMISSIONS"
ROLES_CLAIM = "ROLES"


class AuthService:
    """Верифицирует JWT и собирает permissions пользователя из его claims."""

    def __init__(
        self,
        sign_key: str,
        algorithm: str = "HS256",
        issuer: str = "",
        role_permissions: Mapping[str, Iterable[str]] | None = None,
    ):
        """Параметры проверки токена.

        Args:
            sign_key: секрет (HS*) или публичный ключ в PEM (RS*/ES*).
            algorithm: единственный разрешённый алгоритм подписи.
            issuer: ожидаемый `iss`; пустая строка — не проверять.
            role_permissions: маппинг «роль → permissions» для claim `ROLES`.
        """
        if not sign_key:
            raise ValueError("Ключ подписи JWT не задан (JWT_SECRET_KEY).")
        self.sign_key = sign_key
        self.algorithm = algorithm
        self.issuer = issuer
        self.role_permissions: dict[str, set[str]] = {
            role: set(permissions) for role, permissions in (role_permissions or {}).items()
        }

    def verify_token(self, token: str) -> dict[str, Any]:
        """Проверяет подпись, срок действия (обязательный `exp`) и `iss` токена.

        Raises:
            InvalidTokenError: токен не прошёл верификацию.
        """
        try:
            decoded_token: dict[str, Any] = jwt.decode(
                token,
                self.sign_key,
                algorithms=[self.algorithm],
                issuer=self.issuer or None,
                options={"require": ["exp"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(token) from exc
        return decoded_token

    @staticmethod
    def get_user_id(payload: Mapping[str, Any]) -> str | None:
        """Идентификатор пользователя: claim `USER_ID`, иначе стандартный `sub`."""
        user_id = payload.get(USER_ID_CLAIM) or payload.get("sub")
        return str(user_id) if user_id else None

    def get_permissions(self, payload: Mapping[str, Any]) -> set[str]:
        """Все permissions: прямые из claim `PERMISSIONS` + выданные ролям из claim `ROLES`."""
        permissions = set(_as_str_list(payload.get(PERMISSIONS_CLAIM)))
        for role in _as_str_list(payload.get(ROLES_CLAIM)):
            permissions.update(self.role_permissions.get(role, set()))
        return permissions

    def create_token(
        self,
        user_id: str,
        permissions: Iterable[str] = (),
        roles: Iterable[str] = (),
        expires_in_seconds: int = 3600,
        extra_claims: Mapping[str, Any] | None = None,
    ) -> str:
        """Выпускает токен, который пройдёт `verify_token` (локальная разработка, тесты).

        Для асимметричных алгоритмов (RS*/ES*) `sign_key` должен быть приватным ключом.
        """
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": user_id,
            USER_ID_CLAIM: user_id,
            PERMISSIONS_CLAIM: sorted(set(permissions)),
            ROLES_CLAIM: sorted(set(roles)),
            "iat": now,
            "exp": now + expires_in_seconds,
            **(extra_claims or {}),
        }
        if self.issuer:
            payload["iss"] = self.issuer
        return jwt.encode(payload, self.sign_key, algorithm=self.algorithm)


def _as_str_list(value: Any) -> list[str]:
    """Нормализует claim-список (допускается и одиночная строка)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return []


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Вернуть синглтон сервиса авторизации, собранный из настроек."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService(
            sign_key=settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
            issuer=settings.JWT_ISSUER,
            role_permissions=settings.JWT_ROLE_PERMISSIONS,
        )
    return _auth_service


def reset_auth_service() -> None:
    """Сбросить синглтон (вызывается из lifespan при shutdown и в тестах)."""
    global _auth_service
    _auth_service = None
