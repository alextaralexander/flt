"""Языки интерфейса — единственный источник для backend (SYS-07-R2, R24).

Перечень совпадает с `SUPPORTED_UI_LANGUAGES` фронтенда (`src/lib/i18n/languages.ts`);
добавление языка — только новой версией SYS-07 и одновременной правкой обеих констант.
До этапа 4 (модуль `languages`) здесь же лежит статическая таблица метаданных языков
интерфейса с полями реестра языков SYS-07-R24.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal


UiLanguage = Literal["ru", "en", "ar"]

UI_LANGUAGES: Final[tuple[UiLanguage, ...]] = ("ru", "en", "ar")
DEFAULT_UI_LANGUAGE: Final[UiLanguage] = "ru"
# Cookie явного выбора языка; пишет только frontend, backend читает (SYS-07-R6).
UI_LANGUAGE_COOKIE: Final = "flt_ui_language"


@dataclass(frozen=True)
class UiLanguageInfo:
    """Метаданные языка интерфейса (поля реестра языков SYS-07-R24).

    Attributes:
        code: код BCP-47 (SYS-07-R25).
        name_native: самоназвание языка.
        script: письменность ISO 15924.
        direction: направление письма.
        search_analyzer: группа анализаторов поиска (ADR-014).
        babel_locale: локаль Babel для форматирования на backend (SYS-07-R14, таблица R19).
        fallbacks: цепочка языков для перевода недостающих ключей (как `fallbackLng` фронтенда, SYS-07-R10).
    """

    code: UiLanguage
    name_native: str
    script: str
    direction: Literal["ltr", "rtl"]
    search_analyzer: str
    babel_locale: str
    fallbacks: tuple[UiLanguage, ...]


UI_LANGUAGE_INFO: Final = MappingProxyType(
    {
        "ru": UiLanguageInfo("ru", "Русский", "Cyrl", "ltr", "ru", "ru", ()),
        "en": UiLanguageInfo("en", "English", "Latn", "ltr", "en", "en_GB", ("ru",)),
        "ar": UiLanguageInfo("ar", "العربية", "Arab", "rtl", "ar", "ar", ("en", "ru")),
    }
)


def is_ui_language(value: object) -> bool:
    """Является ли значение кодом поддерживаемого языка интерфейса."""
    return isinstance(value, str) and value in UI_LANGUAGES
