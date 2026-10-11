"""`ModuleRedis` — единственная точка доступа модулей к Redis (ADR-003, SYS-05-R11–R14).

Все ключи автоматически получают префикс модуля (`<module>:<key>`), каждый метод, создающий
или продлевающий ключ, требует `ttl: timedelta` без значения по умолчанию (не больше 24 ч).
Методов без TTL (`persist`, `set` без срока), `KEYS`, `FLUSHDB` и `SCAN` без префикса нет.
Ошибки соединения превращаются в `RedisUnavailableError`, чтобы модули не импортировали `redis`.
"""

import builtins
import json
import re
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.dao.caching.redis_conn import get_redis_client


if TYPE_CHECKING:
    from app.core.dao.caching.locks import RedisLocks
    from app.core.dao.caching.rate_limiter import RateLimiter

MODULE_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_TTL = timedelta(hours=24)

RedisScalar = str | bytes | int | float


class RedisUnavailableError(ConnectionError):
    """Redis недоступен (соединение или таймаут); поведение задаёт вызывающий (SYS-05-R15)."""


def validate_ttl(ttl: timedelta, maximum: timedelta = MAX_TTL) -> int:
    """Проверяет TTL и возвращает его в миллисекундах.

    Args:
        ttl: срок жизни ключа.
        maximum: максимум категории ключа (SYS-05-R13).

    Returns:
        TTL в миллисекундах (не меньше 1).

    Raises:
        ValueError: TTL не `timedelta`, не положителен или больше `maximum`.
    """
    if not isinstance(ttl, timedelta):
        raise ValueError(f"ttl must be timedelta, got {type(ttl).__name__}")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    if ttl > maximum:
        raise ValueError(
            f"ttl {ttl.total_seconds():g}s exceeds maximum {maximum.total_seconds():g}s for this key category"
        )
    return max(1, int(ttl.total_seconds() * 1000))


def _decode(value: Any) -> Any:
    """Приводит ответ Redis к `str`, если клиент вернул `bytes`."""
    return value.decode("utf-8") if isinstance(value, bytes) else value


class ModuleRedis:
    """Обёртка Redis с префиксом модуля и обязательным TTL.

    Экземпляр не хранит состояния между запросами: только префикс и ссылку на клиент
    (свой пул соединений redis-py на процесс). Без явного `client` используется общий клиент
    процесса `get_redis_client()`.

    Args:
        prefix: имя модуля в snake_case (`identity`, `shared_kernel`).
        client: клиент Redis; передаётся в тестах и для имитации отдельных инстансов.

    Raises:
        ValueError: префикс не является именем модуля.
    """

    def __init__(self, prefix: str, *, client: Redis | None = None) -> None:
        """Проверяет префикс и запоминает клиент."""
        if not MODULE_PREFIX_PATTERN.fullmatch(prefix):
            raise ValueError(f"prefix must be a module name in snake_case, got {prefix!r}")
        self._prefix = prefix
        self._client = client

    @property
    def prefix(self) -> str:
        """Префикс модуля (без двоеточия)."""
        return self._prefix

    def full_key(self, key: str) -> str:
        """Полное имя ключа в Redis: `<module>:<key>`."""
        return f"{self._prefix}:{key}"

    async def client(self) -> Redis:
        """Клиент Redis (явный или общий клиент процесса).

        Raises:
            RedisUnavailableError: общий клиент не смог подключиться.
        """
        if self._client is not None:
            return self._client
        try:
            return await get_redis_client()
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            raise RedisUnavailableError(str(exc)) from exc

    async def _call[T](self, awaitable: Awaitable[T]) -> T:
        """Выполняет команду Redis, переводя ошибки соединения в `RedisUnavailableError`."""
        try:
            return await awaitable
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise RedisUnavailableError(str(exc)) from exc

    # --- Строки -----------------------------------------------------------------

    async def get(self, key: str) -> str | None:
        """Значение ключа или `None`, если ключа нет."""
        client = await self.client()
        return cast("str | None", _decode(await self._call(client.get(self.full_key(key)))))

    async def set(self, key: str, value: RedisScalar, *, ttl: timedelta, nx: bool = False) -> bool:
        """Записывает значение с TTL.

        Args:
            key: ключ без префикса модуля.
            value: значение.
            ttl: срок жизни (обязателен, не больше 24 ч).
            nx: записать, только если ключа нет.

        Returns:
            `True`, если значение записано (при `nx=True` — `False`, если ключ уже был).
        """
        ttl_ms = validate_ttl(ttl)
        client = await self.client()
        result = await self._call(client.set(self.full_key(key), value, px=ttl_ms, nx=nx))
        return bool(result)

    async def get_json(self, key: str) -> Any:
        """Значение ключа, разобранное из JSON, или `None`."""
        raw = await self.get(key)
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, *, ttl: timedelta, nx: bool = False) -> bool:
        """Записывает значение, сериализованное в JSON, с TTL (см. `set`)."""
        return await self.set(key, json.dumps(value, separators=(",", ":")), ttl=ttl, nx=nx)

    async def incr(self, key: str, *, ttl: timedelta, amount: int = 1) -> int:
        """Атомарно увеличивает счётчик; TTL ставится при создании ключа и не сдвигается.

        `INCRBY` и `PEXPIRE ... NX` выполняются в одной транзакции `MULTI`, поэтому ключ
        без TTL не возникает даже при обрыве соединения.

        Returns:
            Новое значение счётчика.
        """
        ttl_ms = validate_ttl(ttl)
        client = await self.client()
        full_key = self.full_key(key)
        async with client.pipeline(transaction=True) as pipe:
            pipe.incrby(full_key, amount)
            pipe.pexpire(full_key, ttl_ms, nx=True)
            value, _ = await self._call(pipe.execute())
        return int(value)

    async def delete(self, *keys: str) -> int:
        """Удаляет ключи модуля; возвращает число удалённых."""
        if not keys:
            return 0
        client = await self.client()
        return int(await self._call(client.delete(*(self.full_key(k) for k in keys))))

    async def exists(self, key: str) -> bool:
        """Существует ли ключ."""
        client = await self.client()
        return bool(await self._call(client.exists(self.full_key(key))))

    async def ttl(self, key: str) -> timedelta | None:
        """Оставшийся срок жизни ключа или `None`, если ключа нет."""
        client = await self.client()
        pttl = int(await self._call(client.pttl(self.full_key(key))))
        return timedelta(milliseconds=pttl) if pttl >= 0 else None

    async def expire(self, key: str, *, ttl: timedelta) -> bool:
        """Устанавливает новый TTL существующему ключу; `False`, если ключа нет."""
        ttl_ms = validate_ttl(ttl)
        client = await self.client()
        return bool(await self._call(client.pexpire(self.full_key(key), ttl_ms)))

    # --- Хеши, множества, сортированные множества ----------------------------------

    async def hset(self, key: str, mapping: Mapping[str, RedisScalar], *, ttl: timedelta) -> None:
        """Записывает поля хеша и (пере)устанавливает TTL ключа в одной транзакции."""
        ttl_ms = validate_ttl(ttl)
        client = await self.client()
        full_key = self.full_key(key)
        async with client.pipeline(transaction=True) as pipe:
            pipe.hset(full_key, mapping=dict(mapping))
            pipe.pexpire(full_key, ttl_ms)
            await self._call(pipe.execute())

    async def hget(self, key: str, field: str) -> str | None:
        """Значение поля хеша или `None`."""
        client = await self.client()
        value = await self._call(cast("Awaitable[Any]", client.hget(self.full_key(key), field)))
        return cast("str | None", _decode(value))

    async def hgetall(self, key: str) -> dict[str, str]:
        """Все поля хеша (пустой словарь, если ключа нет)."""
        client = await self.client()
        raw = await self._call(cast("Awaitable[dict[Any, Any]]", client.hgetall(self.full_key(key))))
        return {_decode(k): _decode(v) for k, v in raw.items()}

    async def sadd(self, key: str, *members: RedisScalar, ttl: timedelta) -> int:
        """Добавляет элементы множества и (пере)устанавливает TTL; возвращает число новых элементов."""
        ttl_ms = validate_ttl(ttl)
        client = await self.client()
        full_key = self.full_key(key)
        async with client.pipeline(transaction=True) as pipe:
            pipe.sadd(full_key, *members)
            pipe.pexpire(full_key, ttl_ms)
            added, _ = await self._call(pipe.execute())
        return int(added)

    async def smembers(self, key: str) -> builtins.set[str]:
        """Элементы множества."""
        client = await self.client()
        members = await self._call(cast("Awaitable[builtins.set[Any]]", client.smembers(self.full_key(key))))
        return {_decode(m) for m in members}

    async def srem(self, key: str, *members: RedisScalar) -> int:
        """Удаляет элементы множества; возвращает число удалённых."""
        client = await self.client()
        return int(await self._call(cast("Awaitable[int]", client.srem(self.full_key(key), *members))))

    async def zadd(self, key: str, mapping: Mapping[str, float], *, ttl: timedelta) -> int:
        """Добавляет элементы сортированного множества и (пере)устанавливает TTL."""
        ttl_ms = validate_ttl(ttl)
        client = await self.client()
        full_key = self.full_key(key)
        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(full_key, dict(mapping))
            pipe.pexpire(full_key, ttl_ms)
            added, _ = await self._call(pipe.execute())
        return int(added)

    # --- Pub/sub, обход ключей, Lua ---------------------------------------------------

    async def publish(self, channel: str, message: str | bytes) -> int:
        """Публикует сообщение в канал `<module>:<channel>`; возвращает число получателей.

        Сообщения pub/sub не хранятся (ADR-003, правило 6), поэтому TTL не нужен.
        """
        client = await self.client()
        return int(await self._call(client.publish(self.full_key(channel), message)))

    async def scan_module_keys(self, pattern: str = "*") -> AsyncIterator[str]:
        """Обходит ключи только своего модуля (`SCAN MATCH <module>:<pattern>`), отдаёт их без префикса.

        Предназначен для CLI-команд и тестовых фикстур (SYS-05-R14), не для обработки запросов.
        """
        client = await self.client()
        prefix_length = len(self._prefix) + 1
        iterator = client.scan_iter(match=self.full_key(pattern), count=1000)
        while True:
            try:
                key = await self._call(anext(iterator))
            except StopAsyncIteration:
                return
            yield _decode(key)[prefix_length:]

    async def run_script(self, script: str, keys: Sequence[str], args: Sequence[str | int | float]) -> Any:
        """Выполняет Lua-скрипт shared kernel над ключами своего модуля.

        Только для скриптов `app/core` (блокировки, лимиты, предохранитель): скрипт обязан
        сам ставить TTL создаваемым ключам. Ключи передаются без префикса, аргументы —
        строками (в Lua `ARGV` всегда строки).
        """
        client = await self.client()
        full_keys = [self.full_key(k) for k in keys]
        str_args = [str(arg) for arg in args]
        return await self._call(cast("Awaitable[Any]", client.eval(script, len(full_keys), *full_keys, *str_args)))

    # --- Блокировки и лимиты ------------------------------------------------------------

    @property
    def locks(self) -> RedisLocks:
        """Распределённые блокировки модуля (`<module>:lock:<name>`)."""
        from app.core.dao.caching.locks import RedisLocks

        return RedisLocks(self)

    @property
    def rate_limiter(self) -> RateLimiter:
        """Ограничитель запросов модуля (`<module>:ratelimit:<scope>:<subject>`)."""
        from app.core.dao.caching.rate_limiter import RateLimiter

        return RateLimiter(self)
