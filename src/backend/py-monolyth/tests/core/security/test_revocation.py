"""Отзыв сессий в Redis и fail-open без Redis (ADR-006, разделы 3.2, 3.7; SYS-05-R15).

Интеграционные тесты с реальным Redis (база 15). «Инстансы» — независимые клиенты Redis и
верификаторы: отзыв, записанный одним клиентом, виден всем проверяющим (общее состояние только в Redis).
Ключи `identity:revoked_*` создаёт модуль `identity` (Г.5); здесь их пишет сырой клиент теста.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from redis.asyncio import Redis
from structlog.testing import capture_logs

from app.core.dao.caching.redis_conn import create_redis_client
from app.core.security.errors import UnauthenticatedError
from app.core.security.tokens import (
    REVOKED_SID_KEY,
    REVOKED_USER_KEY,
    RedisRevocationChecker,
    TokenVerifier,
    load_verification_keys,
)
from configs.redis_config import redis_settings
from tests.support.jwt_keys import SigningKeyPair
from tests.support.tokens import TEST_AUDIENCE, TEST_ISSUER, access_claims, issue_access_token


pytestmark = pytest.mark.req("SYS-05-R15")

SKIPPED_METRIC = "flt_auth_revocation_check_skipped_total"
INSTANCES = 3


def _skipped() -> float:
    """Текущее значение счётчика пропущенных проверок отзыва."""
    return REGISTRY.get_sample_value(SKIPPED_METRIC) or 0.0


def _verifier(pair: SigningKeyPair, redis_factory: Callable[[], Awaitable[Redis]] | None = None) -> TokenVerifier:
    """Верификатор «инстанса» с собственным клиентом Redis (или общим клиентом процесса)."""
    keys = load_verification_keys(json.dumps({pair.kid: pair.public_pem}), signing_keys_json="")
    checker = RedisRevocationChecker() if redis_factory is None else RedisRevocationChecker(redis_factory)
    return TokenVerifier(keys, issuer=TEST_ISSUER, audience=TEST_AUDIENCE, revocation=checker)


@pytest_asyncio.fixture
async def instance_clients() -> AsyncIterator[list[Redis]]:
    """Независимые клиенты Redis — по одному на «инстанс»."""
    clients = [create_redis_client(redis_settings) for _ in range(INSTANCES)]
    yield clients
    for client in clients:
        await client.aclose()


def _factory(client: Redis) -> Callable[[], Awaitable[Redis]]:
    """Фабрика, всегда отдающая заданный клиент."""

    async def factory() -> Redis:
        return client

    return factory


@pytest.mark.req("SYS-06-R13")
class TestRevocationAcrossInstances:
    """Отзыв, записанный в Redis, отклоняет токен на любом инстансе."""

    async def test_token_valid_on_every_instance(
        self, jwt_signing_keys: SigningKeyPair, instance_clients: list[Redis]
    ) -> None:
        """Без отзыва токен принимают все инстансы — нужен только публичный ключ."""
        # - Arrange -
        token = issue_access_token(jwt_signing_keys)
        verifiers = [_verifier(jwt_signing_keys, _factory(client)) for client in instance_clients]

        # - Act -
        users = [await verifier.verify(token) for verifier in verifiers]

        # - Assert -
        assert len({user.user_id for user in users}) == 1

    async def test_revoked_session_rejected_everywhere(
        self, jwt_signing_keys: SigningKeyPair, instance_clients: list[Redis], raw_test_redis: Redis
    ) -> None:
        """`identity:revoked_sid:<sid>` → 401 `session_revoked` на всех инстансах; другая сессия — работает."""
        # - Arrange -
        user_id, sid = uuid4(), uuid4()
        revoked = issue_access_token(jwt_signing_keys, access_claims(user_id, sid))
        other_session = issue_access_token(jwt_signing_keys, access_claims(user_id, uuid4()))
        await raw_test_redis.set(REVOKED_SID_KEY.format(sid=sid), "1", ex=600)
        verifiers = [_verifier(jwt_signing_keys, _factory(client)) for client in instance_clients]

        # - Act / Assert -
        for verifier in verifiers:
            with pytest.raises(UnauthenticatedError) as exc_info:
                await verifier.verify(revoked)
            assert exc_info.value.reason == "session_revoked"
            assert (await verifier.verify(other_session)).user_id == user_id

        # - Clean -
        await raw_test_redis.delete(REVOKED_SID_KEY.format(sid=sid))

    async def test_revoked_user_rejects_tokens_issued_before(
        self, jwt_signing_keys: SigningKeyPair, instance_clients: list[Redis], raw_test_redis: Redis
    ) -> None:
        """`identity:revoked_user:<user_id>` = время отзыва: токены с `iat` раньше отклоняются, новые — нет."""
        # - Arrange -
        user_id = uuid4()
        revoked_at = int(time.time())
        before = issue_access_token(jwt_signing_keys, access_claims(user_id, issued_at=revoked_at - 10))
        after = issue_access_token(jwt_signing_keys, access_claims(user_id, issued_at=revoked_at))
        await raw_test_redis.set(REVOKED_USER_KEY.format(user_id=user_id), str(revoked_at), ex=600)
        verifier = _verifier(jwt_signing_keys, _factory(instance_clients[1]))

        # - Act / Assert -
        with pytest.raises(UnauthenticatedError):
            await verifier.verify(before)
        assert (await verifier.verify(after)).user_id == user_id

        # - Clean -
        await raw_test_redis.delete(REVOKED_USER_KEY.format(user_id=user_id))


class TestRedisUnavailable:
    """Без Redis проверка отзыва пропускается: fail-open с метрикой и предупреждением (ADR-006, раздел 3.2)."""

    @pytest.mark.usefixtures("redis_down")
    async def test_valid_token_accepted_and_metric_grows(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Валидный токен принимается, `flt_auth_revocation_check_skipped_total` растёт, в логе warning."""
        # - Arrange -
        token = issue_access_token(jwt_signing_keys)
        before = _skipped()

        # - Act -
        with capture_logs() as logs:
            user = await _verifier(jwt_signing_keys).verify(token)

        # - Assert -
        assert user.roles == ("learner",)
        assert _skipped() == before + 1
        assert any(
            entry["event"] == "core.revocation_check_skipped" and entry["log_level"] == "warning" for entry in logs
        )
        assert all(token not in str(entry) for entry in logs)

    @pytest.mark.usefixtures("redis_down")
    async def test_invalid_signature_still_rejected(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Fail-open касается только отзыва: подпись проверяется всегда, метрика не растёт."""
        # - Arrange -
        before = _skipped()

        # - Act / Assert -
        with pytest.raises(UnauthenticatedError):
            await _verifier(jwt_signing_keys).verify(issue_access_token(jwt_signing_keys, kid="unknown"))
        assert _skipped() == before

    async def test_hanging_redis_is_bounded_by_timeout(self, jwt_signing_keys: SigningKeyPair) -> None:
        """Зависший Redis не держит запрос дольше таймаута проверки — тоже fail-open."""

        # - Arrange -
        async def hanging() -> Redis:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

        verifier = TokenVerifier(
            load_verification_keys(
                json.dumps({jwt_signing_keys.kid: jwt_signing_keys.public_pem}), signing_keys_json=""
            ),
            issuer=TEST_ISSUER,
            audience=TEST_AUDIENCE,
            revocation=RedisRevocationChecker(hanging, timeout_seconds=0.05),
        )
        before = _skipped()

        # - Act -
        started = time.monotonic()
        user = await verifier.verify(issue_access_token(jwt_signing_keys))

        # - Assert -
        assert time.monotonic() - started < 1
        assert user.client == "web"
        assert _skipped() == before + 1
