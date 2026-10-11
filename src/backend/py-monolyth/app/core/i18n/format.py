"""Форматирование дат, чисел и валют для текстов пользователю — Babel (SYS-07-R14, R19, R21).

Локаль Babel берётся из таблицы языков интерфейса (`ru` → `ru`, `en` → `en_GB`, `ar` → `ar`),
числа — всегда с латинскими цифрами (`latn`), календарь — григорианский. Время показывается
в часовом поясе получателя (IANA); на вход принимаются только tz-aware `datetime`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from babel import dates, numbers

from app.core.i18n.languages import UI_LANGUAGE_INFO, is_ui_language


FormatWidth = Literal["short", "medium", "long", "full"]
NUMBERING_SYSTEM = "latn"


def babel_locale(lang: str) -> str:
    """Локаль Babel для языка интерфейса (SYS-07-R19).

    Raises:
        ValueError: язык не входит в `UI_LANGUAGES`.
    """
    if not is_ui_language(lang):
        raise ValueError(f"Unsupported UI language: {lang!r}")
    return UI_LANGUAGE_INFO[lang].babel_locale


def format_datetime(value: datetime, lang: str, tz: str, width: FormatWidth = "medium") -> str:
    """Дата и время в часовом поясе получателя.

    Args:
        value: момент времени с часовым поясом (обычно UTC из PostgreSQL).
        lang: язык интерфейса получателя.
        tz: часовой пояс получателя IANA (`Europe/Moscow`).
        width: формат CLDR.

    Raises:
        ValueError: `value` без часового пояса или язык не поддерживается.
    """
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dates.format_datetime(value, width, tzinfo=dates.get_timezone(tz), locale=babel_locale(lang))


def format_date(value: date | datetime, lang: str, tz: str | None = None, width: FormatWidth = "medium") -> str:
    """Календарная дата; для `datetime` — дата в часовом поясе `tz` получателя.

    Raises:
        ValueError: для `datetime` не передан `tz` или `value` без часового пояса.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None or tz is None:
            raise ValueError("datetime must be timezone-aware and tz is required")
        value = value.astimezone(dates.get_timezone(tz)).date()
    return dates.format_date(value, width, locale=babel_locale(lang))


def format_number(value: int | float | Decimal, lang: str) -> str:
    """Число с разделителями локали и латинскими цифрами."""
    return numbers.format_decimal(value, locale=babel_locale(lang), numbering_system=NUMBERING_SYSTEM)


def format_currency(value: int | float | Decimal, currency: str, lang: str) -> str:
    """Сумма в валюте ISO 4217 по правилам локали и латинскими цифрами."""
    return numbers.format_currency(value, currency, locale=babel_locale(lang), numbering_system=NUMBERING_SYSTEM)
