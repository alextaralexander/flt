"""Источник бизнес-времени shared kernel (ADR-003, раздел 3, правило 3; SYS-05-R42).

Код модулей не вызывает `datetime.now()`, `datetime.utcnow()`, `time.time()` для бизнес-времени:
только `Clock.now()`, который возвращает tz-aware время в UTC (колонки `timestamptz`).
В тестах время подменяет фикстура `frozen_clock` (SYS-10-R17), а не `freezegun`.
`Clock` не хранит состояния, поэтому одинаково работает на любом инстансе.
"""

from datetime import UTC, datetime


class Clock:
    """Единственный источник текущего времени для кода модулей и shared kernel."""

    def now(self) -> datetime:
        """Текущий момент в UTC.

        Returns:
            tz-aware `datetime` с часовым поясом UTC.
        """
        return datetime.now(UTC)
