"""Контроль ключей Redis после теста: TTL, префикс, максимум категории (SYS-05-R12, R13; SYS-10-R6).

Фикстура `redis_no_persistent_keys` после каждого теста с хранилищами обходит тестовую базу
Redis (`SCAN`) и падает с именами ключей, если ключ без TTL (`TTL == -1`), без префикса модуля
или `shared_kernel:`, или с TTL больше максимума своей категории.
"""

from collections.abc import Iterable

from redis.asyncio import Redis


SHARED_KERNEL_PREFIX = "shared_kernel"
# SYS-05-R13: максимум TTL любого ключа — 24 ч; блокировка — 60 с без продления.
MAX_TTL_SECONDS = 24 * 60 * 60
MAX_LOCK_TTL_SECONDS = 60
SCHEDULE_LOCK_PREFIX = "shared_kernel:lock:schedule:"
SCAN_COUNT = 1000


async def find_invalid_keys(client: Redis, module_prefixes: Iterable[str]) -> list[str]:
    """Ключи текущей базы Redis, нарушающие правила SYS-05-R12 и R13.

    Args:
        client: Клиент тестовой базы Redis (`decode_responses` не требуется).
        module_prefixes: Префиксы модулей реестра; `shared_kernel` разрешён всегда.

    Returns:
        Описания нарушений вида `<ключ> (<причина>)`, отсортированные по имени ключа.
    """
    allowed = {*module_prefixes, SHARED_KERNEL_PREFIX}
    problems: list[str] = []
    async for raw_key in client.scan_iter(match="*", count=SCAN_COUNT):
        key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        ttl = await client.ttl(raw_key)
        problem = _key_problem(key, ttl, allowed)
        if problem:
            problems.append(f"{key} ({problem})")
    return sorted(problems)


def _key_problem(key: str, ttl: int, allowed_prefixes: set[str]) -> str:
    """Причина нарушения для одного ключа или пустая строка."""
    prefix, separator, _ = key.partition(":")
    if not separator or prefix not in allowed_prefixes:
        return f"нет префикса модуля из {sorted(allowed_prefixes)} (SYS-05-R11)"
    if ttl == -1:
        return "ttl=-1: ключ без TTL (SYS-05-R12)"
    if ttl > MAX_TTL_SECONDS:
        return f"ttl={ttl} больше 24 ч (SYS-05-R13)"
    if ":lock:" in key and not key.startswith(SCHEDULE_LOCK_PREFIX) and ttl > MAX_LOCK_TTL_SECONDS:
        return f"ttl={ttl}: блокировка дольше {MAX_LOCK_TTL_SECONDS} с (SYS-05-R13)"
    return ""
