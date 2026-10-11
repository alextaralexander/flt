"""Выпуск access JWT (ADR-006, раздел 3.2): EdDSA (Ed25519), `kid` активного ключа, срок 10 минут.

Ключи подписи — секрет `JWT_SIGNING_KEYS` (`{"<kid>": "<PEM приватного ключа>"}`) и `JWT_ACTIVE_KID`
(имена без префикса `IDENTITY_` закреплены ADR-006). Настройки ключей читаются при создании
`TokenIssuer`, поэтому процесс без выпуска токенов (стенд N3, роль `worker`) их не требует.
Проверку выполняет `TokenVerifier` shared kernel по публичным ключам (`JWT_PUBLIC_KEYS` или
выведенным из приватных) — один формат claims для обоих.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jwt.algorithms import OKPAlgorithm
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.ids import new_id
from app.core.time import Clock
from configs.settings import settings as app_settings
from configs.stands import stand_env_file


ACCESS_TTL = timedelta(minutes=10)


class TokenSigningSettings(BaseSettings):
    """Ключи подписи access JWT (секция `identity`, исключение из префикса — ADR-006)."""

    model_config = SettingsConfigDict(extra="ignore", env_file=stand_env_file("identity"))

    JWT_SIGNING_KEYS: SecretStr = Field(description='Приватные ключи Ed25519 по kid: JSON {"<kid>": "<PEM>"}.')
    JWT_ACTIVE_KID: str = Field(description="kid ключа, которым подписываются новые токены.")


@dataclass(frozen=True)
class AccessToken:
    """Выпущенный access-токен."""

    token: str
    expires_in: int


class TokenIssuer:
    """Подписывает access JWT активным ключом.

    Attributes:
        kid: Идентификатор активного ключа.
    """

    def __init__(self, signing: TokenSigningSettings, clock: Clock | None = None) -> None:
        """Загружает активный приватный ключ.

        Raises:
            ValueError: Нет ключа для `JWT_ACTIVE_KID` или ключ не Ed25519.
        """
        keys: dict[str, str] = json.loads(signing.JWT_SIGNING_KEYS.get_secret_value())
        if signing.JWT_ACTIVE_KID not in keys:
            raise ValueError("JWT_ACTIVE_KID отсутствует в JWT_SIGNING_KEYS (ADR-006).")
        private_key = serialization.load_pem_private_key(keys[signing.JWT_ACTIVE_KID].encode(), password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Ключ подписи JWT должен быть Ed25519 (ADR-006).")
        self.kid = signing.JWT_ACTIVE_KID
        self._private_key = private_key
        self._public_keys: dict[str, Ed25519PublicKey] = {}
        for kid, pem in keys.items():
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError(f"Ключ {kid!r} в JWT_SIGNING_KEYS не Ed25519 (ADR-006).")
            self._public_keys[kid] = key.public_key()
        self._clock = clock or Clock()

    def issue_access(
        self,
        user_id: UUID,
        *,
        sid: UUID,
        roles: Sequence[str],
        client: str = "web",
        email_verified: bool = False,
        age_confirmed: bool = False,
    ) -> AccessToken:
        """Access JWT с claims ADR-006 (раздел 3.2)."""
        now = int(self._clock.now().timestamp())
        claims: dict[str, Any] = {
            "iss": app_settings.JWT_ISSUER,
            "aud": app_settings.JWT_AUDIENCE,
            "sub": str(user_id),
            "sid": str(sid),
            "jti": str(new_id()),
            "iat": now,
            "exp": now + int(ACCESS_TTL.total_seconds()),
            "roles": list(roles),
            "client": client,
            "email_verified": email_verified,
            "age_confirmed": age_confirmed,
        }
        token = jwt.encode(claims, self._private_key, algorithm="EdDSA", headers={"kid": self.kid, "typ": "JWT"})
        return AccessToken(token=token, expires_in=int(ACCESS_TTL.total_seconds()))

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        """Публичные ключи в формате JWKS (`OKP`, `Ed25519`) для внешних проверяющих."""
        keys = []
        for kid, public_key in self._public_keys.items():
            jwk: dict[str, Any] = json.loads(OKPAlgorithm.to_jwk(public_key))
            keys.append({**jwk, "kid": kid, "alg": "EdDSA", "use": "sig"})
        return {"keys": keys}


def token_issuer() -> TokenIssuer:
    """`TokenIssuer` из окружения стенда (ошибка — ключи подписи не заданы)."""
    return TokenIssuer(TokenSigningSettings())
