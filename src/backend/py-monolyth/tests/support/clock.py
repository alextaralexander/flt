"""Управляемое время для тестов: подмена `Clock` фикстурой `frozen_clock` (SYS-10-R17)."""

from datetime import UTC, datetime, timedelta


# Момент по умолчанию для тестов, зависящих от времени (SYS-10-R17).
DEFAULT_FROZEN_AT = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class FrozenClock:
    """Остановленные часы: время меняется только вызовами `set` и `advance`."""

    def __init__(self, start: datetime = DEFAULT_FROZEN_AT) -> None:
        """Создаёт часы, остановленные на моменте `start`.

        Args:
            start: Начальный момент (tz-aware).
        """
        self._now = _as_utc(start)

    def now(self) -> datetime:
        """Текущий «замороженный» момент в UTC."""
        return self._now

    def set(self, value: datetime | str) -> None:
        """Переставляет часы на момент `value` (`datetime` или ISO 8601, например `2026-10-10T12:00:00Z`).

        Raises:
            ValueError: Момент без часового пояса.
        """
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
        self._now = _as_utc(moment)

    def advance(self, delta: timedelta) -> None:
        """Сдвигает часы вперёд (или назад при отрицательном `delta`)."""
        self._now += delta


def _as_utc(moment: datetime) -> datetime:
    """Переводит tz-aware момент в UTC; naive-время запрещено (SYS-05-R42)."""
    if moment.tzinfo is None:
        raise ValueError(f"Момент без часового пояса: {moment!r}; ожидается tz-aware время (SYS-05-R42).")
    return moment.astimezone(UTC)
