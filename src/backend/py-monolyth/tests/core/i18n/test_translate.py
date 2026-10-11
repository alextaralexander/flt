"""Тесты переводов backend по каталогам модулей (SYS-07-R13, R8)."""

import json
from pathlib import Path

import pytest

from app.core.i18n import Translator, translate


pytestmark = pytest.mark.no_db

CATALOGS = {
    "ru": {
        "email": {
            "verify": {"subject": "Подтвердите email, {{name}}"},
            "minutes_one": "{{count}} минута",
            "minutes_few": "{{count}} минуты",
            "minutes_many": "{{count}} минут",
            "minutes_other": "{{count}} минуты",
            "only_ru": "Только по-русски",
        }
    },
    "en": {
        "email": {
            "verify": {"subject": "Confirm your email, {{name}}"},
            "minutes_one": "{{count}} minute",
            "minutes_other": "{{count}} minutes",
            "only_en": "English only",
        }
    },
    "ar": {
        "email": {
            "verify": {"subject": "أكد بريدك الإلكتروني، {{name}}"},
            "minutes_zero": "{{count}} دقيقة",
            "minutes_one": "دقيقة واحدة",
            "minutes_two": "دقيقتان",
            "minutes_few": "{{count}} دقائق",
            "minutes_many": "{{count}} دقيقة",
            "minutes_other": "{{count}} دقيقة",
        }
    },
}


@pytest.fixture
def translator(tmp_path: Path) -> Translator:
    """Переводчик по временному каталогу модуля `core_test`."""
    locales = tmp_path / "core_test" / "locales"
    locales.mkdir(parents=True)
    for lang, catalog in CATALOGS.items():
        (locales / f"{lang}.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return Translator(tmp_path)


@pytest.mark.req("SYS-07-R13")
@pytest.mark.parametrize(
    ("lang", "expected"),
    [("ru", "Подтвердите email, Анна"), ("en", "Confirm your email, Анна"), ("ar", "أكد بريدك الإلكتروني، Анна")],
)
def test_translate_with_params(translator: Translator, lang: str, expected: str) -> None:
    """Ключ `<module>:<dotted.key>` переводится на язык получателя с подстановкой `{{name}}`."""
    assert translator.translate("core_test:email.verify.subject", lang, name="Анна") == expected


@pytest.mark.req("SYS-07-R8")
@pytest.mark.parametrize(
    ("lang", "count", "expected"),
    [
        ("ru", 1, "1 минута"),
        ("ru", 3, "3 минуты"),
        ("ru", 5, "5 минут"),
        ("ru", 21, "21 минута"),
        ("en", 1, "1 minute"),
        ("en", 2, "2 minutes"),
        ("ar", 0, "0 دقيقة"),
        ("ar", 2, "دقيقتان"),
        ("ar", 3, "3 دقائق"),
        ("ar", 11, "11 دقيقة"),
    ],
)
def test_plural_forms_by_cldr(translator: Translator, lang: str, count: int, expected: str) -> None:
    """Форма множественного числа выбирается по категории CLDR параметра `count`."""
    assert translator.translate("core_test:email.minutes", lang, count=count) == expected


@pytest.mark.req("SYS-07-R13")
def test_fallback_chain_and_missing_key(translator: Translator) -> None:
    """Недостающий ключ ищется по цепочке `ar` → `en` → `ru`; если его нет нигде — возвращается ключ."""
    assert translator.translate("core_test:email.only_en", "ar") == "English only"
    assert translator.translate("core_test:email.only_ru", "ar") == "Только по-русски"
    assert translator.translate("core_test:email.only_en", "ru") == "core_test:email.only_en"
    assert translator.translate("other_module:email.verify.subject", "ru") == "other_module:email.verify.subject"
    assert translator.translate("core_test:email.verify", "ru") == "core_test:email.verify"


@pytest.mark.req("SYS-07-R13")
@pytest.mark.parametrize("key", ["email.verify.subject", "core_test:", "Core:email", "core_test:email..x"])
def test_invalid_key_rejected(translator: Translator, key: str) -> None:
    """Ключ без модуля или с пустыми сегментами отклоняется."""
    with pytest.raises(ValueError, match="Translation key"):
        translator.translate(key, "ru")


@pytest.mark.req("SYS-07-R13")
def test_unknown_language_rejected(translator: Translator) -> None:
    """Язык вне `UI_LANGUAGES` отклоняется."""
    with pytest.raises(ValueError, match="Unsupported"):
        translator.translate("core_test:email.verify.subject", "de")


@pytest.mark.req("SYS-07-R13")
def test_module_level_translate_reads_app_modules() -> None:
    """`translate()` читает каталоги из `app/modules`; без каталога возвращает ключ."""
    assert translate("no_such_module:some.key", "en") == "no_such_module:some.key"
