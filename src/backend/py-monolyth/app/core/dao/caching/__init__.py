"""Redis shared kernel: `ModuleRedis`, распределённые блокировки и ограничитель запросов (ADR-003).

Модули работают с Redis только через `ModuleRedis(prefix="<module>")`; общий клиент процесса
(`redis_conn.get_redis_client`) и пакет `redis` модулям недоступны (SYS-05-R11).
"""

from app.core.dao.caching.locks import DistributedLock, LockNotAcquiredError, RedisLocks
from app.core.dao.caching.module_redis import ModuleRedis, RedisUnavailableError
from app.core.dao.caching.rate_limiter import RateLimiter, RateLimitResult, RedisFailurePolicy


__all__ = [
    "DistributedLock",
    "LockNotAcquiredError",
    "ModuleRedis",
    "RateLimitResult",
    "RateLimiter",
    "RedisFailurePolicy",
    "RedisLocks",
    "RedisUnavailableError",
]
