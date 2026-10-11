"""Ограничитель запросов: скользящее окно на `ZSET` в Lua (ADR-003, п. 2.7 A; SYS-03-R19; SYS-05-R15).

Ключ `<module>:ratelimit:<scope>:<subject>`. Скрипт атомарно удаляет попытки старше окна,
считает оставшиеся и, если лимит не исчерпан, добавляет новую попытку. Время берётся из Redis
(`TIME`), поэтому окно одинаково для всех инстансов независимо от их часов. Поведение при
недоступном Redis (fail-open или fail-closed) выбирает вызывающий по таблице ADR-003.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from prometheus_client import Counter

from app.core.dao.caching.module_redis import RedisUnavailableError, validate_ttl
from app.core.dao.caching.scripts import RATE_LIMIT_SCRIPT
from app.core.logging.context import app_logger


if TYPE_CHECKING:
    from app.core.dao.caching.module_redis import ModuleRedis

RedisFailurePolicy = Literal["fail_open", "fail_closed"]

RATELIMIT_BYPASSED = Counter(
    "flt_ratelimit_bypassed_total",
    "Проверки лимита, пропущенные из-за недоступности Redis (политика fail-open).",
    ["module", "scope"],
)


@dataclass(frozen=True)
class RateLimitResult:
    """Результат проверки лимита.

    Attributes:
        allowed: попытка разрешена.
        remaining: сколько попыток осталось в окне после этой.
        retry_after: через сколько освободится место (нулевой, если разрешено).
        bypassed: проверка пропущена из-за недоступного Redis (fail-open).
    """

    allowed: bool
    remaining: int
    retry_after: timedelta
    bypassed: bool = False

    @property
    def retry_after_seconds(self) -> int:
        """`retry_after` в целых секундах, округлённых вверх (для заголовка `Retry-After`)."""
        return math.ceil(self.retry_after.total_seconds())


class RateLimiter:
    """Ограничитель запросов модуля поверх `ModuleRedis`."""

    def __init__(self, redis: ModuleRedis) -> None:
        """Принимает `ModuleRedis` модуля-владельца лимита."""
        self._redis = redis

    async def hit(
        self,
        scope: str,
        subject: str,
        limit: int,
        window: timedelta,
        *,
        on_unavailable: RedisFailurePolicy,
    ) -> RateLimitResult:
        """Учитывает попытку субъекта в лимите `scope`.

        Args:
            scope: имя лимита (`quick_test_ip`, `login_email`).
            subject: субъект лимита (IP, `user_id`, идентификатор анонимной сессии).
            limit: сколько попыток разрешено в окне (≥ 1).
            window: длина скользящего окна (≤ 24 ч).
            on_unavailable: поведение без Redis — `fail_open` (пропустить и посчитать метрику
                `flt_ratelimit_bypassed_total`) или `fail_closed` (выбросить `RedisUnavailableError`,
                HTTP-слой отвечает `503 core.service_unavailable`).

        Returns:
            Результат проверки.

        Raises:
            ValueError: некорректный лимит или окно.
            RedisUnavailableError: Redis недоступен при политике `fail_closed`.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        window_ms = validate_ttl(window)
        key = f"ratelimit:{scope}:{subject}"
        try:
            allowed, remaining, retry_ms = await self._redis.run_script(
                RATE_LIMIT_SCRIPT, [key], [limit, window_ms, uuid.uuid4().hex]
            )
        except RedisUnavailableError:
            if on_unavailable == "fail_closed":
                raise
            RATELIMIT_BYPASSED.labels(module=self._redis.prefix, scope=scope).inc()
            app_logger.warning("core.ratelimit_bypassed", module=self._redis.prefix, scope=scope)
            return RateLimitResult(allowed=True, remaining=limit, retry_after=timedelta(0), bypassed=True)
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=int(remaining),
            retry_after=timedelta(milliseconds=int(retry_ms)),
        )
