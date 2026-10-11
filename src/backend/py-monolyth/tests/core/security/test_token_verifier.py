"""Тесты `TokenVerifier`: подпись EdDSA по `kid`, claims, отклонение чужих токенов (ADR-006, раздел 3.2).

Проверка не обращается к БД и `identity`: токен, выпущенный «на одном инстансе», проверяется на
любом по публичному ключу (CLAUDE.md, «Масштабирование и состояние»).
"""

import json
import time
from uuid import uuid4

import jwt
import pytest

from app.core.security.errors import UnauthenticatedError
from app.core.security.tokens import TokenVerifier, load_verification_keys
from tests.support.jwt_keys import SigningKeyPair, generate_signing_key_pair
from tests.support.tokens import TEST_AUDIENCE, TEST_ISSUER, access_claims, issue_access_token


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-03-R21")]


def _verifier(*pairs: SigningKeyPair) -> TokenVerifier:
    """Верификатор с публичными ключами пар и без проверки отзыва (unit-уровень)."""
    keys = load_verification_keys(json.dumps({pair.kid: pair.public_pem for pair in pairs}), signing_keys_json="")
    return TokenVerifier(keys, issuer=TEST_ISSUER, audience=TEST_AUDIENCE, revocation=None)


class TestValidToken:
    """Валидный токен превращается в `UserSecuritySchema`."""

    async def test_claims_are_mapped(self, jwt_signing_keys: SigningKeyPair) -> None:
        """`sub`, `sid`, роли, клиент и флаги подтверждений переносятся в схему; прав в ней ещё нет."""
        # - Arrange -
        user_id, sid = uuid4(), uuid4()
        claims = access_claims(user_id, sid, roles=("learner", "teacher"), client="mobile", age_confirmed=False)
        token = issue_access_token(jwt_signing_keys, claims)

        # - Act -
        user = await _verifier(jwt_signing_keys).verify(token)

        # - Assert -
        assert (user.user_id, user.sid) == (user_id, sid)
        assert user.roles == ("learner", "teacher")
        assert (user.client, user.email_verified, user.age_confirmed) == ("mobile", True, False)
        assert user.permissions == frozenset()

    @pytest.mark.req("SYS-06-R4")
    async def test_permissions_claim_is_ignored(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Права в токене не учитываются: их выводит провайдер ролей при каждой проверке."""
        # - Arrange -
        token = issue_access_token(jwt_signing_keys, access_claims(permissions=["identity:users:read"]))

        # - Act -
        user = await _verifier(jwt_signing_keys).verify(token)

        # - Assert -
        assert user.permissions == frozenset()

    async def test_any_known_kid_is_accepted(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Ротация ключей: токены старого и нового `kid` принимаются, пока оба ключа в конфигурации."""
        # - Arrange -
        new_pair = generate_signing_key_pair()
        verifier = _verifier(jwt_signing_keys, new_pair)

        # - Act -
        old_user = await verifier.verify(issue_access_token(jwt_signing_keys))
        new_user = await verifier.verify(issue_access_token(new_pair))

        # - Assert -
        assert old_user.user_id != new_user.user_id

    async def test_public_keys_are_derived_from_signing_keys(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Без `JWT_PUBLIC_KEYS` публичные ключи выводятся из `JWT_SIGNING_KEYS` (ADR-006, раздел 3.3)."""
        # - Arrange -
        keys = load_verification_keys(
            "", signing_keys_json=json.dumps({jwt_signing_keys.kid: jwt_signing_keys.private_pem})
        )
        verifier = TokenVerifier(keys, issuer=TEST_ISSUER, audience=TEST_AUDIENCE, revocation=None)

        # - Act -
        user = await verifier.verify(issue_access_token(jwt_signing_keys))

        # - Assert -
        assert set(keys) == {jwt_signing_keys.kid}
        assert user.roles == ("learner",)

    async def test_from_settings_uses_session_pair(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Верификатор из настроек процесса принимает токены одноразовой пары тестовой сессии."""
        # - Arrange -
        verifier = TokenVerifier.from_settings(revocation=None)

        # - Act -
        user = await verifier.verify(issue_access_token(jwt_signing_keys))

        # - Assert -
        assert user.client == "web"


class TestRejectedToken:
    """Любое отклонение — `UnauthenticatedError` (`401 core.unauthenticated`) без сырого токена в сообщении."""

    async def _assert_rejected(self, verifier: TokenVerifier, token: str, reason: str = "invalid_token") -> None:
        """Проверка отказа с причиной; токен не попадает в текст ошибки."""
        with pytest.raises(UnauthenticatedError) as exc_info:
            await verifier.verify(token)
        assert exc_info.value.error_code == "core.unauthenticated"
        assert exc_info.value.reason == reason
        assert token not in str(exc_info.value)

    async def test_unknown_kid(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Токен с `kid`, которого нет в конфигурации."""
        await self._assert_rejected(_verifier(jwt_signing_keys), issue_access_token(jwt_signing_keys, kid="other"))

    async def test_signature_of_another_key(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Подпись чужим ключом под известным `kid`."""
        # - Arrange -
        forged = issue_access_token(generate_signing_key_pair(), kid=jwt_signing_keys.kid)

        # - Act / Assert -
        await self._assert_rejected(_verifier(jwt_signing_keys), forged)

    async def test_expired(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Истёкший токен (за пределами leeway 30 с)."""
        # - Arrange -
        expired = issue_access_token(jwt_signing_keys, access_claims(issued_at=time.time() - 3600))

        # - Act / Assert -
        await self._assert_rejected(_verifier(jwt_signing_keys), expired)

    @pytest.mark.parametrize(("claim", "value"), [("iss", "evil"), ("aud", "other-api")])
    async def test_wrong_issuer_or_audience(self, jwt_signing_keys: SigningKeyPair, claim: str, value: str) -> None:
        """Чужие `iss` или `aud`."""
        claims = access_claims()
        claims[claim] = value
        token = issue_access_token(jwt_signing_keys, claims)
        await self._assert_rejected(_verifier(jwt_signing_keys), token)

    @pytest.mark.parametrize("claim", ["exp", "sub", "sid", "iat"])
    async def test_required_claim_missing(self, jwt_signing_keys: SigningKeyPair, claim: str) -> None:
        """Нет обязательного claim из `require=["exp","sub","sid","iat"]`."""
        claims = access_claims()
        del claims[claim]
        token = issue_access_token(jwt_signing_keys, claims)
        await self._assert_rejected(_verifier(jwt_signing_keys), token)

    async def test_non_uuid_subject(self, jwt_signing_keys: SigningKeyPair) -> None:
        """`sub` и `sid` — только UUID."""
        token = issue_access_token(jwt_signing_keys, access_claims(sub="admin"))
        await self._assert_rejected(_verifier(jwt_signing_keys), token)

    async def test_symmetric_algorithm(self, jwt_signing_keys: SigningKeyPair) -> None:
        """HS256 (как в boilerplate) и `alg: none` не принимаются — только EdDSA."""
        # - Arrange -
        hs256 = jwt.encode(access_claims(), "x" * 32, algorithm="HS256", headers={"kid": jwt_signing_keys.kid})
        unsigned = jwt.encode(access_claims(), "", algorithm="none", headers={"kid": jwt_signing_keys.kid})

        # - Act / Assert -
        await self._assert_rejected(_verifier(jwt_signing_keys), hs256)
        await self._assert_rejected(_verifier(jwt_signing_keys), unsigned)

    @pytest.mark.req("SYS-06-R17")
    async def test_agent_token(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Токен агента `flta_…` не JWT пользователя — отклоняется с причиной `agent_token` (ADR-008)."""
        await self._assert_rejected(_verifier(jwt_signing_keys), "flta_" + "a" * 43, reason="agent_token")

    async def test_garbage(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Строка, не являющаяся JWT."""
        await self._assert_rejected(_verifier(jwt_signing_keys), "not-a-jwt")


class TestVerificationKeys:
    """Разбор ключей проверки из конфигурации (ADR-006, раздел 3.3)."""

    def test_no_keys_reject_every_token(self) -> None:
        """Без ключей набор пуст: верификатор отклоняет любой токен (fail-closed)."""
        assert load_verification_keys("", signing_keys_json="") == {}

    def test_malformed_json_is_reported(self) -> None:
        """Некорректный JSON или PEM — ошибка старта, а не молчаливый отказ."""
        with pytest.raises(ValueError, match="JWT_PUBLIC_KEYS"):
            load_verification_keys("{not json", signing_keys_json="")
        with pytest.raises(ValueError, match="JWT_PUBLIC_KEYS"):
            load_verification_keys(json.dumps({"k1": "not a pem"}), signing_keys_json="")

    def test_non_ed25519_key_is_rejected(self) -> None:
        """Ключ другого алгоритма (не Ed25519) не принимается."""
        # - Arrange -
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        pem = (
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )

        # - Act / Assert -
        with pytest.raises(ValueError, match="Ed25519"):
            load_verification_keys(json.dumps({"k1": pem}), signing_keys_json="")
