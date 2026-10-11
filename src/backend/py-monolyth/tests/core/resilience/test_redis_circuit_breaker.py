"""Тесты `RedisCircuitBreaker`: переходы состояний, общее для инстансов состояние в Redis (SYS-08-R16)."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from redis.asyncio import Redis

from app.core.dao.caching import ModuleRedis
from app.core.resilience import CircuitOpenError, CircuitState, RedisCircuitBreaker
from tests.support.eventually import eventually


class ProviderUnavailableError(Exception):
    """Ошибка, которую предохранитель учитывает (аналог `provider_unavailable`)."""


class ProviderAuthError(Exception):
    """Ошибка, которую предохранитель не учитывает (аналог `provider_auth`)."""


def _breaker(redis: ModuleRedis, **overrides: object) -> RedisCircuitBreaker:
    """Предохранитель с параметрами SYS-08-R16 и коротким `open` для тестов."""
    params: dict[str, object] = {
        "name": "openai:api.example.com",
        "window": timedelta(seconds=60),
        "threshold": 5,
        "open_seconds": timedelta(milliseconds=300),
        "half_open_calls": 3,
        "redis": redis,
        "is_failure": lambda exc: isinstance(exc, ProviderUnavailableError),
    }
    params.update(overrides)
    return RedisCircuitBreaker(**params)  # type: ignore[arg-type]


async def _fail(breaker: RedisCircuitBreaker, exc: type[Exception] = ProviderUnavailableError) -> None:
    """Один вызов через предохранитель, завершившийся ошибкой."""
    with pytest.raises(exc):
        async with breaker.guard():
            raise exc("boom")


async def _succeed(breaker: RedisCircuitBreaker) -> None:
    """Один успешный вызов через предохранитель."""
    async with breaker.guard():
        pass


def _instances(redis_instances: Callable[[], Redis], count: int) -> list[RedisCircuitBreaker]:
    """Один и тот же предохранитель на `count` независимых клиентах Redis (имитация инстансов)."""
    return [_breaker(ModuleRedis("shared_kernel", client=redis_instances())) for _ in range(count)]


@pytest.mark.req("SYS-08-R16")
async def test_opens_after_threshold_failures(module_redis: ModuleRedis, raw_test_redis: Redis) -> None:
    """5 учитываемых ошибок в окне открывают предохранитель; при `open` вызов не выполняется."""
    # - Arrange -
    breaker = _breaker(module_redis)
    for _ in range(4):
        await _fail(breaker)
    assert await breaker.state() is CircuitState.CLOSED

    # - Act -
    await _fail(breaker)
    called = False
    with pytest.raises(CircuitOpenError) as exc_info:
        async with breaker.guard():
            called = True

    # - Assert -
    assert await breaker.state() is CircuitState.OPEN
    assert called is False
    assert timedelta(0) < exc_info.value.retry_after <= timedelta(milliseconds=300)
    ttl = await raw_test_redis.ttl("shared_kernel:cb:openai:api.example.com")
    assert 0 < ttl <= 60


@pytest.mark.req("SYS-08-R16")
async def test_ignored_errors_do_not_count(module_redis: ModuleRedis) -> None:
    """Ошибки, которые `is_failure` не учитывает (например `provider_auth`), предохранитель не открывают."""
    # - Arrange -
    breaker = _breaker(module_redis)

    # - Act -
    for _ in range(10):
        await _fail(breaker, ProviderAuthError)

    # - Assert -
    assert await breaker.state() is CircuitState.CLOSED


@pytest.mark.req("SYS-08-R16")
async def test_opens_on_failure_ratio(module_redis: ModuleRedis) -> None:
    """Доля ошибок ≥ 50 % при ≥ 10 вызовах открывает предохранитель даже ниже порога в 5 ошибок."""
    # - Arrange -
    breaker = _breaker(module_redis, threshold=100)
    for _ in range(5):
        await _succeed(breaker)
    for _ in range(4):
        await _fail(breaker)
    assert await breaker.state() is CircuitState.CLOSED

    # - Act -
    await _fail(breaker)

    # - Assert -
    assert await breaker.state() is CircuitState.OPEN


@pytest.mark.req("SYS-08-R16")
async def test_window_resets_counters(module_redis: ModuleRedis) -> None:
    """Ошибки за пределами окна не накапливаются."""
    # - Arrange -
    breaker = _breaker(module_redis, window=timedelta(milliseconds=200))
    for _ in range(4):
        await _fail(breaker)

    # - Act -
    await asyncio.sleep(0.25)
    await _fail(breaker)

    # - Assert -
    assert await breaker.state() is CircuitState.CLOSED


@pytest.mark.req("SYS-08-R16")
async def test_half_open_two_successes_close(module_redis: ModuleRedis) -> None:
    """После `open_seconds` — `half_open`: не больше 3 пробных вызовов, 2 успеха закрывают."""
    # - Arrange -
    breaker = _breaker(module_redis)
    for _ in range(5):
        await _fail(breaker)
    await asyncio.sleep(0.35)

    # - Act -
    await _succeed(breaker)
    assert await breaker.state() is CircuitState.HALF_OPEN
    await _succeed(breaker)

    # - Assert -
    assert await breaker.state() is CircuitState.CLOSED


@pytest.mark.req("SYS-08-R16")
async def test_half_open_limits_trial_calls(module_redis: ModuleRedis) -> None:
    """В `half_open` одновременно пропускается не больше `half_open_calls` пробных вызовов."""
    # - Arrange -
    breaker = _breaker(module_redis)
    for _ in range(5):
        await _fail(breaker)
    await asyncio.sleep(0.35)
    release = asyncio.Event()
    started = 0

    async def trial() -> bool:
        nonlocal started
        try:
            async with breaker.guard():
                started += 1
                await release.wait()
                return True
        except CircuitOpenError:
            return False

    # - Act -
    tasks = [asyncio.create_task(trial()) for _ in range(5)]
    await eventually(lambda: _value(started >= 3))
    await asyncio.sleep(0.05)
    release.set()
    results = await asyncio.gather(*tasks)

    # - Assert -
    assert sum(results) == 3


async def _value(value: bool) -> bool:
    """Обёртка значения в корутину для `eventually`."""
    return value


@pytest.mark.req("SYS-08-R16")
async def test_half_open_failures_reopen(module_redis: ModuleRedis) -> None:
    """Если из пробных вызовов закрыть уже нельзя (2 ошибки из 3), предохранитель снова открывается."""
    # - Arrange -
    breaker = _breaker(module_redis)
    for _ in range(5):
        await _fail(breaker)
    await asyncio.sleep(0.35)

    # - Act -
    await _fail(breaker)
    assert await breaker.state() is CircuitState.HALF_OPEN
    await _fail(breaker)

    # - Assert -
    assert await breaker.state() is CircuitState.OPEN


@pytest.mark.req("SYS-08-R16")
@pytest.mark.req("SYS-05-R51")
async def test_state_is_shared_between_instances(redis_instances: Callable[[], Redis]) -> None:
    """Ошибки с инстанса A открывают предохранитель для инстанса B (состояние общее, в Redis)."""
    # - Arrange -
    a, b, c = _instances(redis_instances, 3)

    # - Act -
    await asyncio.gather(*(_fail(breaker) for breaker in (a, b, c, a, b)))

    # - Assert -
    assert await c.state() is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        async with b.guard():
            pass


@pytest.mark.req("SYS-08-R16")
async def test_concurrent_failures_from_instances_are_counted_once_each(
    redis_instances: Callable[[], Redis],
) -> None:
    """Конкурентные ошибки с трёх инстансов не теряются: 4 ошибки не открывают, 5-я открывает."""
    # - Arrange -
    instances = _instances(redis_instances, 3)

    # - Act -
    await asyncio.gather(*(_fail(instances[i % 3]) for i in range(4)))
    state_after_four = await instances[0].state()
    await _fail(instances[2])

    # - Assert -
    assert state_after_four is CircuitState.CLOSED
    assert await instances[1].state() is CircuitState.OPEN


@pytest.mark.req("SYS-08-R16")
async def test_redis_down_lets_calls_through(down_redis: ModuleRedis) -> None:
    """Без Redis предохранитель не блокирует вызовы (деградация до прямого вызова)."""
    # - Arrange -
    breaker = _breaker(down_redis)

    # - Act -
    async with breaker.guard():
        called = True

    # - Assert -
    assert called is True
    assert await breaker.state() is CircuitState.CLOSED


@pytest.mark.req("SYS-08-R16")
def test_invalid_parameters_rejected(module_redis: ModuleRedis) -> None:
    """Параметры предохранителя проверяются при создании."""
    with pytest.raises(ValueError, match="half_open"):
        _breaker(module_redis, half_open_calls=1, half_open_successes=2)
    with pytest.raises(ValueError, match="threshold"):
        _breaker(module_redis, threshold=0)
