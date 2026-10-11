"""Выпуск access JWT в тестах shared kernel до `TokenIssuer` модуля `identity` (Г.5).

Токены подписываются одноразовой Ed25519-парой тестовой сессии (`tests/support/jwt_keys.py`)
в формате ADR-006, раздел 3.2: заголовок `{"alg": "EdDSA", "kid": ...}`, claims `iss`, `aud`,
`sub`, `sid`, `jti`, `iat`, `exp`, `roles`, `client`, `email_verified`, `age_confirmed`.
"""

import time
from typing import Any
from uuid import UUID, uuid4

import jwt

from tests.support.jwt_keys import SigningKeyPair


TEST_ISSUER = "flt"
TEST_AUDIENCE = "flt-api"
ACCESS_TTL_SECONDS = 600


def access_claims(
    user_id: UUID | None = None,
    sid: UUID | None = None,
    *,
    roles: tuple[str, ...] = ("learner",),
    issued_at: float | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Claims access-токена по ADR-006 с подстановкой значений теста.

    Args:
        user_id: `sub`; по умолчанию — новый UUID.
        sid: Сессия (`family_id`); по умолчанию — новый UUID.
        roles: Роли пользователя.
        issued_at: `iat` (unix-время); по умолчанию — сейчас.
        **overrides: Переопределения и дополнительные claims (значение None удаляет claim).

    Returns:
        Словарь claims.
    """
    now = int(time.time() if issued_at is None else issued_at)
    claims: dict[str, Any] = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": str(user_id or uuid4()),
        "sid": str(sid or uuid4()),
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + ACCESS_TTL_SECONDS,
        "roles": list(roles),
        "client": "web",
        "email_verified": True,
        "age_confirmed": True,
    }
    for name, value in overrides.items():
        if value is None:
            claims.pop(name, None)
        else:
            claims[name] = value
    return claims


def issue_access_token(pair: SigningKeyPair, claims: dict[str, Any] | None = None, *, kid: str | None = None) -> str:
    """Подписывает claims приватным ключом пары (EdDSA) с `kid` в заголовке."""
    return jwt.encode(
        claims or access_claims(),
        pair.private_pem,
        algorithm="EdDSA",
        headers={"kid": kid or pair.kid, "typ": "JWT"},
    )
