"""Тесты языков интерфейса и типа кода языка (SYS-07-R2, R24, R25)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.i18n import DEFAULT_UI_LANGUAGE, UI_LANGUAGE_INFO, UI_LANGUAGES, LanguageCode
from app.core.i18n.types import is_language_code


pytestmark = pytest.mark.no_db


@pytest.mark.req("SYS-07-R2")
def test_ui_languages() -> None:
    """Языки интерфейса — `ru`, `en`, `ar`; по умолчанию `ru`; все коды проходят валидацию BCP-47."""
    assert UI_LANGUAGES == ("ru", "en", "ar")
    assert DEFAULT_UI_LANGUAGE == "ru"
    assert DEFAULT_UI_LANGUAGE in UI_LANGUAGES
    assert all(is_language_code(code) for code in UI_LANGUAGES)


@pytest.mark.req("SYS-07-R24")
def test_ui_language_table() -> None:
    """Статическая таблица языков интерфейса: направление, письменность, локаль Babel (таблица R19)."""
    assert set(UI_LANGUAGE_INFO) == set(UI_LANGUAGES)
    assert UI_LANGUAGE_INFO["ar"].direction == "rtl"
    assert UI_LANGUAGE_INFO["ru"].direction == UI_LANGUAGE_INFO["en"].direction == "ltr"
    assert {code: info.babel_locale for code, info in UI_LANGUAGE_INFO.items()} == {
        "ru": "ru",
        "en": "en_GB",
        "ar": "ar",
    }
    assert UI_LANGUAGE_INFO["ar"].script == "Arab"
    with pytest.raises(TypeError):
        UI_LANGUAGE_INFO["de"] = UI_LANGUAGE_INFO["en"]  # type: ignore[index]


@pytest.mark.req("SYS-07-R25")
@pytest.mark.parametrize("code", ["en", "ru", "ar", "zh-Hans", "zh-Hant", "pt-BR", "sr-Cyrl", "fil"])
def test_language_code_accepts_canonical(code: str) -> None:
    """Канонические теги BCP-47 проходят валидацию `LanguageCode`."""
    assert TypeAdapter(LanguageCode).validate_python(code) == code


@pytest.mark.req("SYS-07-R25")
@pytest.mark.parametrize("code", ["EN", "zh_CN", "zh-cn", "zh-hans", "pt-br", "english", "", "e"])
def test_language_code_rejects_non_canonical(code: str) -> None:
    """Неканонические формы (`zh_CN`, `zh-cn`, `EN`) отклоняются."""
    with pytest.raises(ValidationError):
        TypeAdapter(LanguageCode).validate_python(code)
