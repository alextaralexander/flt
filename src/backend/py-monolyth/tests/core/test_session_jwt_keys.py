"""Тесты одноразовой Ed25519-пары ключей подписи JWT тестовой сессии (ADR-006 §3.3, SYS-06-R20)."""

import json
import os

import jwt
import pytest

from tests.support.jwt_keys import JWT_ENV_NAMES, SigningKeyPair, generate_signing_key_pair


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-06-R20")]


def test_session_pair_is_installed_in_environment(jwt_signing_keys: SigningKeyPair) -> None:
    """Корневой conftest выставил `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID`, `JWT_PUBLIC_KEYS` в форматах ADR-006."""
    # - Assert -
    assert all(os.environ.get(name) for name in JWT_ENV_NAMES)
    assert os.environ["JWT_ACTIVE_KID"] == jwt_signing_keys.kid
    assert set(json.loads(os.environ["JWT_SIGNING_KEYS"])) == {jwt_signing_keys.kid}
    assert jwt_signing_keys.private_pem.startswith("-----BEGIN PRIVATE KEY-----")  # pragma: allowlist secret
    assert jwt_signing_keys.public_pem.startswith("-----BEGIN PUBLIC KEY-----")


def test_token_signed_by_private_key_verifies_with_public(jwt_signing_keys: SigningKeyPair) -> None:
    """Токен EdDSA, подписанный приватным ключом пары, проверяется её публичным ключом по `kid`."""
    # - Arrange -
    claims = {"sub": "00000000-0000-7000-8000-000000000001", "iss": "flt", "aud": "flt-api"}

    # - Act -
    token = jwt.encode(claims, jwt_signing_keys.private_pem, algorithm="EdDSA", headers={"kid": jwt_signing_keys.kid})
    decoded = jwt.decode(token, jwt_signing_keys.public_pem, algorithms=["EdDSA"], audience="flt-api", issuer="flt")

    # - Assert -
    assert jwt.get_unverified_header(token)["kid"] == jwt_signing_keys.kid
    assert decoded["sub"] == claims["sub"]


def test_each_generated_pair_is_unique() -> None:
    """Пара одноразовая: новые генерации дают новые `kid` и ключи."""
    # - Act -
    first, second = generate_signing_key_pair(), generate_signing_key_pair()

    # - Assert -
    assert first.kid != second.kid
    assert first.private_pem != second.private_pem
    assert first.kid.startswith("pytest-")
