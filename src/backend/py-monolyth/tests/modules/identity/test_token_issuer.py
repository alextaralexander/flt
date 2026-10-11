"""Выпуск access JWT `TokenIssuer` и его проверка `TokenVerifier` shared kernel (ADR-006, раздел 3.2; SYS-02-R19)."""

import os
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.security import TokenVerifier, load_verification_keys
from app.modules.identity.services.passwords import hash_password, verify_password
from app.modules.identity.services.token_issuer import ACCESS_TTL, TokenIssuer, TokenSigningSettings, token_issuer
from configs.settings import settings


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-02-R19")]


def _verifier() -> TokenVerifier:
    """Верификатор по публичным ключам сессии тестов, без проверки отзыва."""
    keys = load_verification_keys(os.environ["JWT_PUBLIC_KEYS"], signing_keys_json="")
    return TokenVerifier(keys, issuer=settings.JWT_ISSUER, audience=settings.JWT_AUDIENCE, revocation=None)


async def test_issued_access_token_is_accepted_by_verifier() -> None:
    """Токен, выпущенный активным ключом, проходит проверку: `sub`, `sid`, роли, срок 10 минут."""
    # - Arrange -
    issuer = token_issuer()
    user_id, sid = uuid4(), uuid4()

    # - Act -
    access = issuer.issue_access(user_id, sid=sid, roles=["learner"], email_verified=True, age_confirmed=True)
    user = await _verifier().verify(access.token)

    # - Assert -
    assert (user.user_id, user.sid, user.roles) == (user_id, sid, ("learner",))
    assert access.expires_in == int(ACCESS_TTL.total_seconds()) == 600


def test_jwks_exposes_public_key_of_active_kid() -> None:
    """JWKS содержит ключ `OKP`/`Ed25519` с `kid` активного ключа и без приватной части."""
    # - Act -
    jwks = token_issuer().jwks()

    # - Assert -
    [key] = jwks["keys"]
    assert key["kid"] == os.environ["JWT_ACTIVE_KID"]
    assert (key["kty"], key["crv"], key["alg"], key["use"]) == ("OKP", "Ed25519", "EdDSA", "sig")
    assert "d" not in key


def test_active_kid_must_exist() -> None:
    """`JWT_ACTIVE_KID` без ключа в `JWT_SIGNING_KEYS` — ошибка конфигурации при создании."""
    # - Arrange -
    signing = TokenSigningSettings(JWT_SIGNING_KEYS=SecretStr(os.environ["JWT_SIGNING_KEYS"]), JWT_ACTIVE_KID="missing")

    # - Act / Assert -
    with pytest.raises(ValueError, match="JWT_ACTIVE_KID"):
        TokenIssuer(signing)


def test_password_hash_is_argon2id_and_verifies() -> None:
    """Пароль хранится как argon2id; неверный пароль и испорченный хэш не проходят."""
    # - Act -
    password_hash = hash_password("correct horse battery")

    # - Assert -
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct horse battery") is True
    assert verify_password(password_hash, "wrong") is False
    assert verify_password("not-a-hash", "wrong") is False
