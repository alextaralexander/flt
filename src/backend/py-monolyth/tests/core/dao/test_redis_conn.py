"""Тесты общего Redis-клиента процесса: standalone на реальном Redis, Sentinel — по конфигурации."""

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis, Sentinel
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.dao.caching import redis_conn
from configs.redis_config import RedisMode, RedisSettings


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-05-R17")]


class TestRedisClient:
    """Клиент создаётся по режиму из настроек (Arrange / Act / Assert)."""

    async def test_standalone_client_is_shared_and_closed(self) -> None:
        """Повторный вызов в том же loop возвращает тот же клиент; close освобождает его."""
        # - Act -
        first = await redis_conn.get_redis_client()
        second = await redis_conn.get_redis_client()
        pong = await first.ping()
        await redis_conn.close_redis_client()

        # - Assert -
        assert first is second
        assert pong is True
        assert redis_conn._redis_client is None

    def test_sentinel_mode_uses_master_from_sentinel(self) -> None:
        """В режиме sentinel клиент — мастер `REDIS_SENTINEL_MASTER`, найденный через Sentinel."""
        # - Arrange -
        config = RedisSettings.model_construct(
            REDIS_MODE=RedisMode.SENTINEL,
            REDIS_SENTINEL_HOSTS="sentinel-0:26379,sentinel-1:26379",
            REDIS_SENTINEL_MASTER="flt",
            REDIS_DB=0,
            REDIS_PASSWORD=SecretStr("redis-secret"),  # pragma: allowlist secret
            REDIS_DECODE_RESPONSES=True,
        )

        # - Act -
        client = redis_conn.create_redis_client(config)

        # - Assert -
        pool_kwargs = client.connection_pool.connection_kwargs
        assert isinstance(client, Redis)
        assert client.connection_pool.service_name == "flt"  # type: ignore[attr-defined]
        assert isinstance(client.connection_pool.sentinel_manager, Sentinel)  # type: ignore[attr-defined]
        assert pool_kwargs["password"] == "redis-secret"  # pragma: allowlist secret

    async def test_unreachable_redis_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Недоступный Redis — исключение при первом обращении, клиент не кэшируется."""
        # - Arrange -
        await redis_conn.close_redis_client()
        broken = RedisSettings.model_construct(
            REDIS_MODE=RedisMode.STANDALONE,
            REDIS_HOST="127.0.0.1",
            REDIS_PORT=1,
            REDIS_DB=0,
            REDIS_PASSWORD=SecretStr(""),
            REDIS_DECODE_RESPONSES=True,
        )
        monkeypatch.setattr(redis_conn, "redis_settings", broken)

        # - Act / Assert -
        with pytest.raises(RedisConnectionError):
            await redis_conn.get_redis_client()
        assert redis_conn._redis_client is None
