"""Распределённые блокировки в Redis (ADR-003, п. 2.7 A; SYS-05-R13, R20).

`SET <module>:lock:<name> <token> NX PX <ttl>`; освобождение и продление — Lua-скриптами
с проверкой токена владельца, поэтому снять или продлить чужую блокировку нельзя, а истёкшая
снимается сама. Блокировка — средство избежать двойной работы, а не гарантия корректности:
защищаемая операция обязана быть идемпотентной или защищённой инвариантом PostgreSQL.
"""

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from app.core.dao.caching.module_redis import MAX_TTL, validate_ttl
from app.core.dao.caching.scripts import LOCK_EXTEND_SCRIPT, LOCK_RELEASE_SCRIPT
from app.core.logging.context import app_logger


if TYPE_CHECKING:
    from app.core.dao.caching.module_redis import ModuleRedis

# Максимальный TTL блокировки без продления; блокировка планировщика — до интервала задачи (SYS-05-R13).
LOCK_MAX_TTL = timedelta(seconds=60)
SCHEDULE_LOCK_OWNER = "shared_kernel"
SCHEDULE_LOCK_NAME_PREFIX = "schedule:"
DEFAULT_RETRY_INTERVAL = timedelta(milliseconds=50)


class LockNotAcquiredError(Exception):
    """Блокировку не удалось взять за время ожидания `wait`."""

    def __init__(self, name: str) -> None:
        """Запоминает имя блокировки."""
        self.name = name
        super().__init__(f"Lock {name!r} is held by another owner")


@dataclass
class DistributedLock:
    """Взятая блокировка: имя, токен владельца, текущий TTL.

    Объект живёт только внутри `async with locks.acquire(...)` одного запроса или задачи.
    """

    redis: ModuleRedis
    name: str
    ttl: timedelta
    max_ttl: timedelta
    token: str = field(default_factory=lambda: secrets.token_hex(16))

    @property
    def key(self) -> str:
        """Ключ блокировки без префикса модуля: `lock:<name>`."""
        return f"lock:{self.name}"

    async def extend(self, ttl: timedelta | None = None) -> bool:
        """Продлевает блокировку, если она всё ещё принадлежит владельцу.

        Args:
            ttl: новый TTL (по умолчанию — исходный); не больше максимума категории.

        Returns:
            `True`, если продлена; `False`, если блокировка истекла или перехвачена.
        """
        new_ttl = ttl or self.ttl
        ttl_ms = validate_ttl(new_ttl, self.max_ttl)
        result = await self.redis.run_script(LOCK_EXTEND_SCRIPT, [self.key], [self.token, ttl_ms])
        return bool(result)

    async def release(self) -> bool:
        """Снимает блокировку, если она принадлежит владельцу; `False` — уже истекла или чужая."""
        result = await self.redis.run_script(LOCK_RELEASE_SCRIPT, [self.key], [self.token])
        return bool(result)


class RedisLocks:
    """Фабрика распределённых блокировок модуля."""

    def __init__(self, redis: ModuleRedis) -> None:
        """Принимает `ModuleRedis` модуля-владельца."""
        self._redis = redis

    def _max_ttl(self, name: str) -> timedelta:
        """Максимальный TTL блокировки по её категории (SYS-05-R13)."""
        if self._redis.prefix == SCHEDULE_LOCK_OWNER and name.startswith(SCHEDULE_LOCK_NAME_PREFIX):
            return MAX_TTL
        return LOCK_MAX_TTL

    async def try_acquire(self, name: str, ttl: timedelta) -> DistributedLock | None:
        """Одна попытка взять блокировку; `None`, если она занята.

        Raises:
            ValueError: TTL больше максимума категории (60 с; для планировщика — 24 ч).
            RedisUnavailableError: Redis недоступен (политика fail-closed, ADR-003).
        """
        max_ttl = self._max_ttl(name)
        validate_ttl(ttl, max_ttl)
        lock = DistributedLock(redis=self._redis, name=name, ttl=ttl, max_ttl=max_ttl)
        acquired = await self._redis.set(lock.key, lock.token, ttl=ttl, nx=True)
        return lock if acquired else None

    @asynccontextmanager
    async def acquire(
        self,
        name: str,
        ttl: timedelta,
        wait: timedelta = timedelta(0),
        *,
        heartbeat: bool = False,
        retry_interval: timedelta = DEFAULT_RETRY_INTERVAL,
    ) -> AsyncIterator[DistributedLock]:
        """Берёт блокировку `<module>:lock:<name>` на время блока `async with`.

        Args:
            name: имя блокировки (`outbox:identity`, `schedule:identity.purge_tokens`).
            ttl: TTL блокировки (≤ 60 с; для `shared_kernel:lock:schedule:*` — ≤ 24 ч).
            wait: сколько ждать освобождения занятой блокировки.
            heartbeat: продлевать блокировку фоново каждые `ttl / 3`, пока выполняется блок.
            retry_interval: пауза между попытками при ожидании.

        Yields:
            Взятая блокировка; при выходе из блока она снимается (если ещё принадлежит владельцу).

        Raises:
            LockNotAcquiredError: блокировка занята дольше `wait`.
            ValueError: TTL больше максимума категории.
            RedisUnavailableError: Redis недоступен.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait.total_seconds()
        while True:
            lock = await self.try_acquire(name, ttl)
            if lock is not None:
                break
            if loop.time() >= deadline:
                raise LockNotAcquiredError(name)
            await asyncio.sleep(retry_interval.total_seconds())

        heartbeat_task = asyncio.create_task(self._heartbeat(lock)) if heartbeat else None
        try:
            yield lock
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            try:
                await lock.release()
            except ConnectionError:
                # Блокировка истечёт сама по TTL; ошибку снятия не выдаём вместо ошибки блока.
                app_logger.warning("core.lock_release_failed", lock=name)

    @staticmethod
    async def _heartbeat(lock: DistributedLock) -> None:
        """Фоновое продление блокировки каждые `ttl / 3`, пока она принадлежит владельцу."""
        interval = lock.ttl.total_seconds() / 3
        while True:
            await asyncio.sleep(interval)
            try:
                if not await lock.extend():
                    app_logger.warning("core.lock_lost", lock=lock.name)
                    return
            except ConnectionError:
                app_logger.warning("core.lock_extend_failed", lock=lock.name)
