"""Предохранитель внешних вызовов с общим для всех инстансов состоянием в Redis (SYS-08-R16).

Состояние хранится в хеше `<module>:cb:<name>` модуля-владельца (`llm_gateway:cb:<kind>:<host>`):
`closed` → (порог ошибок в окне или доля ошибок) → `open` на `open_seconds` → `half_open`
(не больше `half_open_calls` пробных вызовов; `half_open_successes` успехов закрывают,
невозможность набрать их снова открывает). Переходы выполняются Lua-скриптами атомарно, время
берётся из Redis (`TIME`), поэтому все инстансы видят одно состояние и одни часы. Класс
`py_main_lib.adapters.circuit_breaker.CircuitBreaker` не используется: его состояние живёт
в памяти процесса.

При недоступном Redis предохранитель не блокирует вызовы (деградация до прямого вызова,
предупреждение в лог): отказ Redis не должен останавливать обращения к провайдерам.
"""

import asyncio
import enum
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from app.core.dao.caching import ModuleRedis, RedisUnavailableError
from app.core.dao.caching.module_redis import validate_ttl
from app.core.dao.caching.scripts import CIRCUIT_AFTER_SCRIPT, CIRCUIT_BEFORE_SCRIPT, CIRCUIT_STATE_SCRIPT
from app.core.logging.context import app_logger


class CircuitState(enum.StrEnum):
    """Состояние предохранителя."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Предохранитель открыт: вызов не выполняется.

    Attributes:
        name: имя предохранителя.
        retry_after: через сколько стоит повторить.
    """

    def __init__(self, name: str, retry_after: timedelta) -> None:
        """Запоминает имя предохранителя и время до повтора."""
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit {name!r} is open, retry after {retry_after.total_seconds():g}s")


# Режимы допуска вызова, которые возвращает CIRCUIT_BEFORE_SCRIPT.
_REJECTED = 0
_CLOSED_CALL = 1
_TRIAL_CALL = 2

# Исходы вызова для CIRCUIT_AFTER_SCRIPT.
_SUCCESS = "success"
_FAILURE = "failure"
_IGNORED = "ignored"


def _count_every_error(exc: BaseException) -> bool:
    """По умолчанию учитывается любое исключение, кроме отмены задачи."""
    return not isinstance(exc, asyncio.CancelledError)


class RedisCircuitBreaker:
    """Предохранитель с общим состоянием в Redis.

    Экземпляр не хранит состояния: всё в ключе `<module>:cb:<name>` с TTL
    `max(window, open_seconds)`; при потере ключа предохранитель закрыт.

    Args:
        name: имя предохранителя внутри модуля (`openai:api.openai.com`).
        window: окно подсчёта ошибок в состоянии `closed` (по SYS-08-R16 — 60 с).
        threshold: число учитываемых ошибок в окне, открывающее предохранитель (5).
        open_seconds: длительность состояния `open` (30 с).
        half_open_calls: число пробных вызовов в `half_open` (3).
        redis: `ModuleRedis` модуля-владельца (`ModuleRedis("llm_gateway")`).
        half_open_successes: успехов пробных вызовов, закрывающих предохранитель (2).
        failure_ratio: доля ошибок, открывающая предохранитель при `min_calls` вызовах (0,5).
        min_calls: минимальное число вызовов в окне для проверки доли (10).
        is_failure: какие исключения учитывать; остальные (например `provider_auth`)
            пробрасываются без влияния на состояние.

    Raises:
        ValueError: некорректные параметры.
    """

    def __init__(
        self,
        name: str,
        window: timedelta,
        threshold: int,
        open_seconds: timedelta,
        half_open_calls: int,
        *,
        redis: ModuleRedis,
        half_open_successes: int = 2,
        failure_ratio: float = 0.5,
        min_calls: int = 10,
        is_failure: Callable[[BaseException], bool] = _count_every_error,
    ) -> None:
        """Проверяет параметры предохранителя."""
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if half_open_successes < 1 or half_open_calls < half_open_successes:
            raise ValueError("half_open_calls must be >= half_open_successes >= 1")
        if not 0 < failure_ratio <= 1 or min_calls < 1:
            raise ValueError("failure_ratio must be in (0, 1] and min_calls >= 1")
        self.name = name
        self._window_ms = validate_ttl(window)
        self._open_ms = validate_ttl(open_seconds)
        self._ttl_ms = max(self._window_ms, self._open_ms)
        self._threshold = threshold
        self._half_open_calls = half_open_calls
        self._half_open_successes = half_open_successes
        self._failure_ratio = failure_ratio
        self._min_calls = min_calls
        self._is_failure = is_failure
        self._redis = redis

    @property
    def key(self) -> str:
        """Ключ состояния без префикса модуля: `cb:<name>`."""
        return f"cb:{self.name}"

    async def state(self) -> CircuitState:
        """Текущее состояние (для метрик и диагностики); без Redis — `closed`."""
        try:
            raw = await self._redis.run_script(CIRCUIT_STATE_SCRIPT, [self.key], [self._open_ms])
        except RedisUnavailableError:
            return CircuitState.CLOSED
        return CircuitState(raw.decode() if isinstance(raw, bytes) else raw)

    async def _before(self) -> int:
        """Допуск вызова: режим `closed`/`trial` или `CircuitOpenError`."""
        try:
            mode, retry_ms = await self._redis.run_script(
                CIRCUIT_BEFORE_SCRIPT,
                [self.key],
                [self._window_ms, self._open_ms, self._half_open_calls, self._ttl_ms],
            )
        except RedisUnavailableError:
            app_logger.warning("core.circuit_breaker_redis_unavailable", breaker=self.name)
            return _CLOSED_CALL
        if int(mode) == _REJECTED:
            raise CircuitOpenError(self.name, timedelta(milliseconds=int(retry_ms)))
        return int(mode)

    async def _after(self, mode: int, outcome: str) -> None:
        """Учитывает исход вызова в общем состоянии."""
        try:
            await self._redis.run_script(
                CIRCUIT_AFTER_SCRIPT,
                [self.key],
                [
                    mode,
                    outcome,
                    self._threshold,
                    self._failure_ratio,
                    self._min_calls,
                    self._half_open_calls,
                    self._half_open_successes,
                    self._window_ms,
                    self._ttl_ms,
                ],
            )
        except RedisUnavailableError:
            app_logger.warning("core.circuit_breaker_redis_unavailable", breaker=self.name)

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Выполняет блок под защитой предохранителя.

        Yields:
            Управление вызывающему, если вызов допущен.

        Raises:
            CircuitOpenError: предохранитель открыт или пробные вызовы `half_open` исчерпаны.
        """
        mode = await self._before()
        try:
            yield
        except BaseException as exc:
            outcome = _FAILURE if self._is_failure(exc) else _IGNORED
            await self._after(mode, outcome)
            raise
        await self._after(mode, _SUCCESS)
