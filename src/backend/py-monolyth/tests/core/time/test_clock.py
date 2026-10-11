"""Тесты `Clock` и его подмены фикстурой `frozen_clock` (SYS-05-R42, SYS-10-R17)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.time import Clock
from tests.support.clock import DEFAULT_FROZEN_AT, FrozenClock


pytestmark = pytest.mark.no_db


@pytest.mark.req("SYS-05-R42")
def test_now_is_timezone_aware_utc() -> None:
    """`Clock.now()` возвращает tz-aware время в UTC."""
    # - Act -
    moment = Clock().now()

    # - Assert -
    assert moment.tzinfo is UTC
    assert abs(datetime.now(UTC) - moment) < timedelta(seconds=5)


@pytest.mark.req("SYS-10-R17")
class TestFrozenClock:
    """Фикстура `frozen_clock` управляет временем всех экземпляров `Clock`."""

    def test_clock_is_frozen_at_default_moment(self, frozen_clock: FrozenClock) -> None:
        """По умолчанию часы стоят на 2026-10-10T12:00:00Z."""
        # - Act / Assert -
        assert Clock().now() == DEFAULT_FROZEN_AT == datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

    def test_set_from_iso_string(self, frozen_clock: FrozenClock) -> None:
        """`set` принимает строку ISO 8601 и переводит момент в UTC."""
        # - Act -
        frozen_clock.set("2026-10-11T15:30:00+03:00")

        # - Assert -
        assert Clock().now() == datetime(2026, 10, 11, 12, 30, tzinfo=UTC)
        assert Clock().now().tzinfo is UTC

    def test_advance_moves_time(self, frozen_clock: FrozenClock) -> None:
        """`advance` сдвигает время на интервал без ожидания."""
        # - Act -
        frozen_clock.advance(timedelta(minutes=10))

        # - Assert -
        assert Clock().now() == DEFAULT_FROZEN_AT + timedelta(minutes=10)

    def test_naive_moment_is_rejected(self, frozen_clock: FrozenClock) -> None:
        """naive-время запрещено (SYS-05-R42)."""
        # - Act / Assert -
        with pytest.raises(ValueError, match="без часового пояса"):
            frozen_clock.set(datetime(2026, 10, 10, 12, 0))

    def test_other_timezone_is_normalized(self) -> None:
        """Начальный момент в другом поясе приводится к UTC."""
        # - Arrange -
        moscow = timezone(timedelta(hours=3))

        # - Act -
        clock = FrozenClock(datetime(2026, 10, 10, 15, 0, tzinfo=moscow))

        # - Assert -
        assert clock.now() == DEFAULT_FROZEN_AT
