"""Circuit Breaker для защиты от каскадных сбоев."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Coroutine, List, Optional, TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Состояние circuit breaker."""

    CLOSED = "closed"  # Нормальная работа
    OPEN = "open"  # Отказ, запросы не проходят
    HALF_OPEN = "half_open"  # Тестовый режим


@dataclass
class CircuitBreakerConfig:
    """Конфигурация Circuit Breaker."""

    # Failure thresholds
    failure_threshold: int = 5  # Количество ошибок для открытия
    failure_rate_threshold: float = 0.5  # Процент ошибок для открытия (0.0-1.0)

    # Recovery
    recovery_timeout: float = 30.0  # Секунд до перехода в HALF_OPEN
    half_open_max_calls: int = 3  # Тестовых вызовов в HALF_OPEN

    # Success threshold
    success_threshold: int = 2  # Успешных вызовов для закрытия из HALF_OPEN

    # Sliding window
    window_size: int = 10  # Размер окна для подсчёта ошибок

    # Exceptions to track
    tracked_exceptions: tuple = (Exception,)  # Какие исключения считать failures

    # S3 specific exceptions
    s3_retriable_errors: tuple = ()  # Исключения для retry без открытия circuit


@dataclass
class CircuitStats:
    """Статистика Circuit Breaker."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Отклонено из-за OPEN

    # Timing
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    last_state_change: float = field(default_factory=time.perf_counter)

    # State transitions
    times_opened: int = 0
    times_closed: int = 0


class CircuitBreakerException(Exception):
    """Исключение когда circuit breaker открыт."""

    def __init__(self, breaker_name: str, state: CircuitState, message: str = ""):
        self.breaker_name = breaker_name
        self.state = state
        super().__init__(message or f"Circuit breaker '{breaker_name}' is {state.value}")


class CircuitBreaker:

    def __init__(
        self,
        name: str = "default",
        config: Optional[CircuitBreakerConfig] = None,
        on_open: Optional[Callable[["CircuitBreaker"], None]] = None,
        on_close: Optional[Callable[["CircuitBreaker"], None]] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.on_open = on_open
        self.on_close = on_close

        # State
        self._state = CircuitState.CLOSED
        self._failure_window: List[float] = []  # Timestamps of failures
        self._half_open_calls = 0
        self._half_open_successes = 0

        # Stats
        self.stats = CircuitStats()

        # Lock for thread safety
        self._lock = asyncio.Lock()

        logger.info(
            "[CB:%s] Initialized: failure_threshold=%d, recovery_timeout=%.1fs",
            self.name,
            self.config.failure_threshold,
            self.config.recovery_timeout,
        )

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self._state == CircuitState.HALF_OPEN

    def can_execute(self) -> bool:
        """Проверяет можно ли выполнить запрос."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # Check if recovery timeout passed
            if self._should_attempt_recovery():
                self._transition_to_half_open()
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            # Allow limited calls in half-open
            return self._half_open_calls < self.config.half_open_max_calls

        return False

    def _should_attempt_recovery(self) -> bool:
        """Проверяет прошёл ли recovery timeout."""
        if self.stats.last_failure_time is None:
            return True

        elapsed = time.perf_counter() - self.stats.last_failure_time
        return elapsed >= self.config.recovery_timeout

    def record_success(self):
        """Записывает успешный вызов."""
        self.stats.total_calls += 1
        self.stats.successful_calls += 1
        self.stats.last_success_time = time.perf_counter()

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1

            if self._half_open_successes >= self.config.success_threshold:
                self._transition_to_closed()

    def record_failure(self, exception: Optional[Exception] = None):
        """Записывает неудачный вызов."""
        now = time.perf_counter()

        self.stats.total_calls += 1
        self.stats.failed_calls += 1
        self.stats.last_failure_time = now

        # Add to sliding window
        self._failure_window.append(now)
        self._cleanup_window()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens circuit
            self._transition_to_open()

        elif self._state == CircuitState.CLOSED:
            # Check if we should open
            if self._should_open():
                self._transition_to_open()

    def _cleanup_window(self):
        """Очищает старые записи из sliding window."""
        now = time.perf_counter()
        # Keep only last N failures within reasonable time
        cutoff = now - 60.0  # Last minute
        self._failure_window = [t for t in self._failure_window[-self.config.window_size :] if t > cutoff]

    def _should_open(self) -> bool:
        """Проверяет нужно ли открыть circuit."""
        recent_failures = len(self._failure_window)

        # Check failure count threshold
        if recent_failures >= self.config.failure_threshold:
            return True

        # Check failure rate threshold
        if self.stats.total_calls >= self.config.window_size:
            recent_total = min(self.stats.total_calls, self.config.window_size)
            failure_rate = recent_failures / recent_total
            if failure_rate >= self.config.failure_rate_threshold:
                return True

        return False

    def _transition_to_open(self):
        """Переход в состояние OPEN."""
        old_state = self._state
        self._state = CircuitState.OPEN
        self.stats.times_opened += 1
        self.stats.last_state_change = time.perf_counter()

        logger.warning(
            "[CB:%s] OPENED: %s → OPEN (failures=%d)",
            self.name,
            old_state.value,
            len(self._failure_window),
        )

        if self.on_open:
            try:
                self.on_open(self)
            except Exception as e:
                logger.error("[CB:%s] on_open callback failed: %s", self.name, e)

    def _transition_to_half_open(self):
        """Переход в состояние HALF_OPEN."""
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        self._half_open_successes = 0
        self.stats.last_state_change = time.perf_counter()

        logger.info(
            "[CB:%s] HALF_OPEN: testing with %d calls",
            self.name,
            self.config.half_open_max_calls,
        )

    def _transition_to_closed(self):
        """Переход в состояние CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_window.clear()
        self.stats.times_closed += 1
        self.stats.last_state_change = time.perf_counter()

        logger.info("[CB:%s] CLOSED: recovered successfully", self.name)

        if self.on_close:
            try:
                self.on_close(self)
            except Exception as e:
                logger.error("[CB:%s] on_close callback failed: %s", self.name, e)

    def reset(self):
        """Сбрасывает circuit breaker вручную."""
        self._state = CircuitState.CLOSED
        self._failure_window.clear()
        self._half_open_calls = 0
        self._half_open_successes = 0
        self.stats.last_state_change = time.perf_counter()

        logger.info("[CB:%s] Reset manually", self.name)

    async def __aenter__(self):
        """Context manager entry."""
        if not self.can_execute():
            self.stats.rejected_calls += 1
            raise CircuitBreakerException(
                self.name,
                self._state,
                f"Circuit breaker '{self.name}' is {self._state.value}, "
                f"retry after {self.config.recovery_timeout:.0f}s",
            )

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None:
            self.record_success()
        elif issubclass(exc_type, self.config.tracked_exceptions):
            self.record_failure(exc_val)
        # Don't suppress exception
        return False

    def __call__(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., Coroutine[Any, Any, T]]:
        """Decorator usage."""

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            async with self:
                return await func(*args, **kwargs)

        return wrapper

    def get_stats(self) -> dict:
        """Возвращает статистику."""
        return {
            "name": self.name,
            "state": self._state.value,
            "total_calls": self.stats.total_calls,
            "successful_calls": self.stats.successful_calls,
            "failed_calls": self.stats.failed_calls,
            "rejected_calls": self.stats.rejected_calls,
            "failure_window_size": len(self._failure_window),
            "times_opened": self.stats.times_opened,
            "times_closed": self.stats.times_closed,
            "time_in_state": time.perf_counter() - self.stats.last_state_change,
        }


class S3CircuitBreaker(CircuitBreaker):
    def __init__(
        self,
        name: str = "s3",
        config: Optional[CircuitBreakerConfig] = None,
        **kwargs,
    ):
        # Default S3-specific config
        if config is None:
            config = CircuitBreakerConfig(
                failure_threshold=3,
                failure_rate_threshold=0.5,
                recovery_timeout=30.0,
                half_open_max_calls=2,
                success_threshold=2,
            )

        super().__init__(name=name, config=config, **kwargs)

        # S3-specific exception tracking
        self._throttle_count = 0
        self._last_throttle_time: Optional[float] = None

    def record_throttle(self):
        """Записывает throttling событие от S3."""
        now = time.perf_counter()
        self._throttle_count += 1
        self._last_throttle_time = now

        logger.warning(
            "[CB:%s] S3 throttled (count=%d)",
            self.name,
            self._throttle_count,
        )

    def should_throttle(self) -> bool:
        """Проверяет нужно ли throttle запросы."""
        if self._last_throttle_time is None:
            return False

        # Throttle for 5 seconds after S3 throttle
        elapsed = time.perf_counter() - self._last_throttle_time
        return elapsed < 5.0

    def get_throttle_delay(self) -> float:
        """Возвращает рекомендуемую задержку при throttling."""
        if not self.should_throttle():
            return 0.0

        # Exponential backoff based on throttle count
        return float(min(0.5 * (2 ** min(self._throttle_count - 1, 4)), 8.0))
