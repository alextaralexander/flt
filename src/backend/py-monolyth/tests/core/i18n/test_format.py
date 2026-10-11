"""Тесты форматирования Babel на трёх локалях и двух часовых поясах (SYS-07-R14, R19, R21)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core.i18n import format_currency, format_date, format_datetime, format_number


pytestmark = pytest.mark.no_db

MOMENT = datetime(2026, 10, 10, 21, 30, tzinfo=UTC)
WESTERN_DIGITS = set("0123456789")
EASTERN_ARABIC_DIGITS = set("٠١٢٣٤٥٦٧٨٩")


@pytest.mark.req("SYS-07-R14")
@pytest.mark.req("SYS-07-R19")
@pytest.mark.parametrize(("lang", "expected"), [("ru", "1 234,5"), ("en", "1,234.5"), ("ar", "1,234.5")])
def test_format_number(lang: str, expected: str) -> None:
    """Числа — разделители локали и латинские цифры, в том числе для `ar`."""
    assert format_number(1234.5, lang).replace("\xa0", " ").replace(" ", " ") == expected


@pytest.mark.req("SYS-07-R14")
def test_format_currency() -> None:
    """Валюта — по правилам локали, латинские цифры."""
    assert format_currency(Decimal("1234.5"), "RUB", "ru").replace("\xa0", " ") == "1 234,50 ₽"
    assert format_currency(Decimal("1234.5"), "EUR", "en") == "€1,234.50"
    arabic = format_currency(Decimal("1234.5"), "USD", "ar")
    assert "1,234.50" in arabic
    assert not set(arabic) & EASTERN_ARABIC_DIGITS


@pytest.mark.req("SYS-07-R14")
@pytest.mark.req("SYS-07-R21")
def test_format_datetime_uses_recipient_timezone() -> None:
    """Один момент времени в `Europe/Moscow` и `Asia/Tokyo` даёт разные часы и даты."""
    moscow = format_datetime(MOMENT, "en", "Europe/Moscow")
    tokyo = format_datetime(MOMENT, "en", "Asia/Tokyo")
    assert moscow == "11 Oct 2026, 00:30:00"
    assert tokyo == "11 Oct 2026, 06:30:00"
    assert format_date(MOMENT, "ru", "Europe/Moscow") == "11 окт. 2026\u202fг."
    assert format_date(MOMENT, "en", "America/New_York") == "10 Oct 2026"
    assert format_date(date(2026, 10, 10), "en") == "10 Oct 2026"


@pytest.mark.req("SYS-07-R19")
def test_arabic_datetime_uses_western_digits() -> None:
    """Арабская локаль: латинские цифры и григорианский календарь."""
    text = format_datetime(MOMENT, "ar", "Asia/Riyadh")
    assert "2026" in text
    assert not set(text) & EASTERN_ARABIC_DIGITS


@pytest.mark.req("SYS-07-R21")
def test_naive_datetime_and_unknown_language_rejected() -> None:
    """Время без часового пояса и язык вне `UI_LANGUAGES` отклоняются."""
    naive = datetime(2026, 10, 10, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        format_datetime(naive, "ru", "Europe/Moscow")
    with pytest.raises(ValueError, match="timezone-aware"):
        format_date(MOMENT, "ru")
    with pytest.raises(ValueError, match="Unsupported"):
        format_number(1, "de")
