"""Проверка access JWT на любом инстансе (ADR-006, разделы 3.2, 3.3).

`TokenVerifier.verify` проверяет подпись EdDSA по `kid` набором публичных ключей из конфигурации,
`iss`, `aud`, обязательные claims и отзыв сессии в Redis. Проверка не обращается к БД и к модулю
`identity`: токен, выпущенный на одном инстансе, проверяется на любом. При недоступном Redis
проверка отзыва пропускается (fail-open, окно ≤ 600 с — решение пользователя 2026-10-10) с
предупреждением в лог и метрикой `flt_auth_revocation_check_skipped_total`.

Ключи и настройки неизменны в процессе; состояния между запросами верификатор не хранит.
"""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from prometheus_client import Counter
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.dao.caching.redis_conn import get_redis_client
from app.core.logging.context import get_logger
from app.core.security.errors import UnauthenticatedError
from app.core.security.schemas import UserSecuritySchema
from configs.settings import settings


logger = get_logger("flt.core.security")

ALGORITHM = "EdDSA"
LEEWAY_SECONDS = 30
REQUIRED_CLAIMS = ("exp", "sub", "sid", "iat")
AGENT_TOKEN_PREFIX = "flta_"  # nosec B105 — префикс формата токена агента (ADR-008), не секрет
# Ключи отзыва пишет модуль identity (ADR-006, раздел 3.1); ядро их только читает.
REVOKED_SID_KEY = "identity:revoked_sid:{sid}"
REVOKED_USER_KEY = "identity:revoked_user:{user_id}"
REVOCATION_TIMEOUT_SECONDS = 0.5

REVOCATION_CHECK_SKIPPED = Counter(
    "flt_auth_revocation_check_skipped",
    "Access-токены, принятые без проверки отзыва сессии из-за недоступного Redis (ADR-006).",
)


def _parse_keys_json(raw: str, variable: str) -> dict[str, str]:
    """JSON `{"<kid>": "<PEM>"}` из переменной окружения."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{variable}: ожидается JSON {{"<kid>": "<PEM>"}}.') from exc
    if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
        raise ValueError(f'{variable}: ожидается JSON-объект строк {{"<kid>": "<PEM>"}}.')
    return parsed


def load_verification_keys(public_keys_json: str, *, signing_keys_json: str) -> dict[str, Ed25519PublicKey]:
    """Публичные ключи проверки по `kid` (ADR-006, раздел 3.3).

    Источник — `JWT_PUBLIC_KEYS`; если переменная пуста, ключи выводятся из приватных ключей
    `JWT_SIGNING_KEYS` (в монолите задаётся один секрет, выделенный сервис получает только публичные).

    Args:
        public_keys_json: Значение `JWT_PUBLIC_KEYS` (`{"<kid>": "<PEM публичного ключа>"}`) или пусто.
        signing_keys_json: Значение `JWT_SIGNING_KEYS` (`{"<kid>": "<PEM приватного ключа>"}`) или пусто.

    Returns:
        Ключи Ed25519 по `kid`; пустой словарь — ключей нет, любой токен будет отклонён.

    Raises:
        ValueError: JSON или PEM некорректны либо ключ не Ed25519 (ошибка конфигурации при старте).
    """
    keys: dict[str, Ed25519PublicKey] = {}
    if public_keys_json.strip():
        for kid, pem in _parse_keys_json(public_keys_json, "JWT_PUBLIC_KEYS").items():
            try:
                public_key = serialization.load_pem_public_key(pem.encode())
            except ValueError as exc:
                raise ValueError(f"JWT_PUBLIC_KEYS: ключ {kid!r} не читается как PEM.") from exc
            if not isinstance(public_key, Ed25519PublicKey):
                raise ValueError(f"JWT_PUBLIC_KEYS: ключ {kid!r} не Ed25519 (ADR-006, EdDSA).")
            keys[kid] = public_key
        return keys
    if signing_keys_json.strip():
        for kid, pem in _parse_keys_json(signing_keys_json, "JWT_SIGNING_KEYS").items():
            try:
                private_key = serialization.load_pem_private_key(pem.encode(), password=None)
            except ValueError as exc:
                raise ValueError(f"JWT_SIGNING_KEYS: ключ {kid!r} не читается как PEM.") from exc
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError(f"JWT_SIGNING_KEYS: ключ {kid!r} не Ed25519 (ADR-006, EdDSA).")
            keys[kid] = private_key.public_key()
    return keys


class RevocationStatus(StrEnum):
    """Результат проверки отзыва сессии."""

    ACTIVE = "active"
    REVOKED = "revoked"
    SKIPPED = "skipped"


class RedisRevocationChecker:
    """Проверка отзыва по ключам `identity:revoked_sid:<sid>` и `identity:revoked_user:<user_id>`.

    Один pipeline из двух `GET`; ограничен таймаутом, чтобы зависший Redis не держал запросы.
    Любая ошибка Redis даёт `SKIPPED` (fail-open, ADR-006, раздел 3.2; SYS-05-R15).
    """

    def __init__(
        self,
        redis_factory: Callable[[], Awaitable[Redis]] = get_redis_client,
        *,
        timeout_seconds: float = REVOCATION_TIMEOUT_SECONDS,
    ) -> None:
        """Сохраняет фабрику клиента Redis (по умолчанию — общий клиент процесса) и таймаут."""
        self._redis_factory = redis_factory
        self._timeout_seconds = timeout_seconds

    async def check(self, *, sid: UUID, user_id: UUID, issued_at: float) -> RevocationStatus:
        """Отозвана ли сессия `sid` или все сессии пользователя, выпущенные до отметки отзыва.

        Args:
            sid: Сессия токена.
            user_id: Пользователь токена.
            issued_at: `iat` токена (unix-время).

        Returns:
            `REVOKED` — сессия отозвана или `iat` меньше отметки `revoked_user`; `ACTIVE` — нет;
            `SKIPPED` — Redis недоступен, проверка пропущена.
        """
        try:
            async with asyncio.timeout(self._timeout_seconds):
                client = await self._redis_factory()
                async with client.pipeline(transaction=False) as pipe:
                    pipe.get(REVOKED_SID_KEY.format(sid=sid))
                    pipe.get(REVOKED_USER_KEY.format(user_id=user_id))
                    revoked_sid, revoked_user_at = await pipe.execute()
        except (RedisError, OSError, TimeoutError) as exc:
            REVOCATION_CHECK_SKIPPED.inc()
            logger.warning("core.revocation_check_skipped", error=type(exc).__name__)
            return RevocationStatus.SKIPPED
        if revoked_sid is not None:
            return RevocationStatus.REVOKED
        if revoked_user_at is not None and issued_at < float(revoked_user_at):
            return RevocationStatus.REVOKED
        return RevocationStatus.ACTIVE


class TokenVerifier:
    """Проверка access JWT EdDSA по набору публичных ключей и отзыву в Redis (ADR-006, раздел 3.2)."""

    def __init__(
        self,
        keys: Mapping[str, Ed25519PublicKey],
        *,
        issuer: str,
        audience: str,
        revocation: RedisRevocationChecker | None,
        leeway_seconds: int = LEEWAY_SECONDS,
    ) -> None:
        """Сохраняет неизменяемую конфигурацию проверки.

        Args:
            keys: Публичные ключи по `kid`.
            issuer: Ожидаемый `iss` (`JWT_ISSUER`).
            audience: Ожидаемый `aud` (`JWT_AUDIENCE`).
            revocation: Проверка отзыва; None — без неё (только unit-тесты и выделенные проверки).
            leeway_seconds: Допуск расхождения часов для `exp` и `iat`.
        """
        self._keys = dict(keys)
        self._issuer = issuer
        self._audience = audience
        self._revocation = revocation
        self._leeway = leeway_seconds

    @classmethod
    def from_settings(cls, revocation: RedisRevocationChecker | None = None) -> TokenVerifier:
        """Верификатор из настроек процесса: `JWT_PUBLIC_KEYS` (или `JWT_SIGNING_KEYS`), `JWT_ISSUER`, `JWT_AUDIENCE`.

        Args:
            revocation: Проверка отзыва; по умолчанию — по общему клиенту Redis процесса.
        """
        keys = load_verification_keys(
            settings.JWT_PUBLIC_KEYS, signing_keys_json=os.environ.get("JWT_SIGNING_KEYS", "")
        )
        return cls(
            keys,
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            revocation=RedisRevocationChecker() if revocation is None else revocation,
        )

    def _decode(self, token: str) -> dict[str, Any]:
        """Проверяет подпись, срок, издателя, аудиторию и обязательные claims."""
        if token.startswith(AGENT_TOKEN_PREFIX):
            raise UnauthenticatedError("agent_token")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._keys.get(kid) if isinstance(kid, str) else None
            if key is None:
                raise UnauthenticatedError("invalid_token")
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except jwt.PyJWTError as exc:
            raise UnauthenticatedError("invalid_token") from exc
        # PyJWT проверяет `require` только для зарегистрированных claims; `sid` проверяется явно.
        if any(claims.get(name) is None for name in REQUIRED_CLAIMS):
            raise UnauthenticatedError("invalid_token")
        return claims

    async def verify(self, token: str) -> UserSecuritySchema:
        """Проверяет access-токен и возвращает пользователя без грантов (их добавляет `auth_user`).

        Args:
            token: Access JWT из cookie `__Host-flt_access` или заголовка `Authorization: Bearer`.

        Returns:
            Пользователь с `user_id`, `sid`, ролями, клиентом и флагами подтверждений.

        Raises:
            UnauthenticatedError: Токен не прошёл проверку (`invalid_token`), это токен агента
                (`agent_token`) или сессия отозвана (`session_revoked`).
        """
        claims = self._decode(token)
        try:
            user = UserSecuritySchema(
                user_id=claims["sub"],
                sid=claims["sid"],
                roles=tuple(claims.get("roles") or ()),
                client=claims.get("client") or "web",
                email_verified=bool(claims.get("email_verified", False)),
                age_confirmed=bool(claims.get("age_confirmed", False)),
            )
        except (ValueError, TypeError) as exc:
            raise UnauthenticatedError("invalid_token") from exc

        if self._revocation is not None:
            status = await self._revocation.check(sid=user.sid, user_id=user.user_id, issued_at=float(claims["iat"]))
            if status is RevocationStatus.REVOKED:
                raise UnauthenticatedError("session_revoked")
        return user
