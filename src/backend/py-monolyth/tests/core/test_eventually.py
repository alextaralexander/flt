"""Тесты ожидания асинхронного эффекта `eventually` (SYS-10-R17)."""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R17")]

Eventually = Callable[..., Awaitable[Any]]


async def test_returns_first_truthy_result(eventually: Eventually) -> None:
    """Опрос идёт до первого истинного результата, он и возвращается."""
    # - Arrange -
    attempts: list[int] = []

    def probe() -> list[int] | None:
        attempts.append(1)
        return attempts if len(attempts) >= 3 else None

    # - Act -
    result = await eventually(probe, timeout=1.0, interval=0.01)

    # - Assert -
    assert result == [1, 1, 1]


async def test_accepts_async_probe_with_asserts(eventually: Eventually) -> None:
    """Асинхронная проверка с `assert` повторяется, пока не пройдёт."""
    # - Arrange -
    calls: list[int] = []

    async def probe() -> bool:
        calls.append(1)
        assert len(calls) > 1
        return True

    # - Act / Assert -
    assert await eventually(probe, timeout=1.0, interval=0.01) is True


async def test_timeout_raises_with_last_error(eventually: Eventually) -> None:
    """По таймауту — `AssertionError` с последней ошибкой проверки в причине."""

    # - Arrange -
    def probe() -> bool:
        raise AssertionError("ещё нет")

    # - Act -
    with pytest.raises(AssertionError, match="не выполнилось") as error:
        await eventually(probe, timeout=0.05, interval=0.01)

    # - Assert -
    assert str(error.value.__cause__) == "ещё нет"
