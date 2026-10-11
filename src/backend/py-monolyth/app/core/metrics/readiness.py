"""Readiness по роли процесса и liveness с информационными деталями (ADR-010, раздел 3.4; SYS-10-R33).

- `ReadinessProbe` выполняет проверки роли: `api` — PostgreSQL, `worker` — PostgreSQL и Kafka;
  Redis в readiness не входит (его отказ снял бы с балансировки все инстансы сразу, ADR-003).
  Результат кэшируется в процессе на `READINESS_CACHE_SECONDS` — это неизменяемый для
  всех инстансов способ снизить нагрузку частых проверок HAProxy (SYS-05-R2 разрешает).
- `health_details` — детали `/v1/health`: доступность Redis; код ответа от них не зависит.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import text

from app.core.dao.caching.redis_conn import get_redis_client
from app.core.dao.db_helpers.db_connection import get_engine
from app.core.logging.context import get_logger
from app.core.metrics.process_metrics import REDIS_UP


logger = get_logger("flt.core.readiness")

READINESS_CACHE_SECONDS = 5.0
CHECK_TIMEOUT_SECONDS = 2.0

Check = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class ReadinessResult:
    """Итог проверок готовности.

    Attributes:
        ready: Все проверки роли прошли.
        checks: Статус каждой проверки: `ok` или текст ошибки.
        timestamp: Время выполнения проверок (Unix).
    """

    ready: bool
    checks: dict[str, str]
    timestamp: float


@dataclass
class ReadinessProbe:
    """Проверки готовности роли с кэшем результата.

    Attributes:
        checks: Имя проверки → корутина, бросающая исключение при недоступности зависимости.
        cache_seconds: Срок жизни результата в процессе.
        clock: Монотонные часы (подменяются в тестах).
    """

    checks: Mapping[str, Check]
    cache_seconds: float = READINESS_CACHE_SECONDS
    clock: Callable[[], float] = time.monotonic
    _cached: ReadinessResult | None = field(default=None, init=False)
    _cached_at: float = field(default=0.0, init=False)

    async def run(self) -> ReadinessResult:
        """Результат проверок; повторный вызов в пределах `cache_seconds` проверки не повторяет."""
        now = self.clock()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached
        statuses: dict[str, str] = {}
        for name, check in self.checks.items():
            try:
                await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
            except Exception as exc:  # любая ошибка зависимости означает «не готов»
                statuses[name] = f"error: {type(exc).__name__}"
            else:
                statuses[name] = "ok"
        result = ReadinessResult(
            ready=all(value == "ok" for value in statuses.values()), checks=statuses, timestamp=time.time()
        )
        if not result.ready:
            logger.warning("core.readiness_failed", checks=statuses)
        self._cached, self._cached_at = result, now
        return result


async def check_postgres() -> None:
    """`SELECT 1` в пуле процесса."""
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def check_redis() -> None:
    """`PING` Redis; обновляет `flt_redis_up`."""
    try:
        client = await get_redis_client()
        await asyncio.wait_for(client.ping(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception:
        REDIS_UP.set(0)
        raise
    REDIS_UP.set(1)


async def health_details() -> dict[str, str]:
    """Информационные детали liveness: `redis` — `ok` или `unavailable`."""
    try:
        await check_redis()
    except Exception:  # liveness не зависит от Redis
        return {"redis": "unavailable"}
    return {"redis": "ok"}
