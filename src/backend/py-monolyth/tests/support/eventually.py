"""Ожидание асинхронного эффекта опросом с таймаутом вместо фиксированных пауз (SYS-10-R17)."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import cast


DEFAULT_TIMEOUT_SECONDS = 2.0
# Шаг опроса в unit- и интеграционных тестах; тесты стенда N3 передают 0,5 с (SYS-10-R17).
DEFAULT_INTERVAL_SECONDS = 0.05

type Probe[T] = Callable[[], T | Awaitable[T]]


async def eventually[T](
    probe: Probe[T],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,  # noqa: ASYNC109 — сигнатура eventually(…, timeout=…) задана SYS-10-R17
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> T:
    """Опрашивает `probe`, пока результат не станет истинным, и возвращает его.

    `probe` — синхронная или асинхронная функция без аргументов; `AssertionError` внутри неё
    считается «ещё не выполнено» (удобно для проверок с `assert`).

    Args:
        probe: Проверка состояния.
        timeout: Предельное время ожидания, с.
        interval: Пауза между попытками, с.

    Returns:
        Первый истинный результат `probe`.

    Raises:
        AssertionError: За `timeout` секунд условие не выполнилось (с последней ошибкой как причиной).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_error: AssertionError | None = None
    last_result: object = None
    while True:
        try:
            result = probe()
            if inspect.isawaitable(result):
                result = await result
            if result:
                return cast("T", result)
            last_result = result
        except AssertionError as error:
            last_error = error
        if loop.time() >= deadline:
            message = f"Условие не выполнилось за {timeout} с; последний результат: {last_result!r}"
            raise AssertionError(message) from last_error
        await asyncio.sleep(interval)
