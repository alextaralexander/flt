"""i18n backend shared kernel: языки интерфейса, язык запроса, переводы, форматирование (SYS-07)."""

from app.core.i18n.format import format_currency, format_date, format_datetime, format_number
from app.core.i18n.languages import (
    DEFAULT_UI_LANGUAGE,
    UI_LANGUAGE_COOKIE,
    UI_LANGUAGE_INFO,
    UI_LANGUAGES,
    UiLanguage,
    UiLanguageInfo,
)
from app.core.i18n.request_language import (
    RequestLanguage,
    pick_from_accept_language,
    request_language,
    resolve_request_language,
)
from app.core.i18n.translate import Translator, translate
from app.core.i18n.types import LanguageCode


__all__ = [
    "DEFAULT_UI_LANGUAGE",
    "UI_LANGUAGES",
    "UI_LANGUAGE_COOKIE",
    "UI_LANGUAGE_INFO",
    "LanguageCode",
    "RequestLanguage",
    "Translator",
    "UiLanguage",
    "UiLanguageInfo",
    "format_currency",
    "format_date",
    "format_datetime",
    "format_number",
    "pick_from_accept_language",
    "request_language",
    "resolve_request_language",
    "translate",
]
