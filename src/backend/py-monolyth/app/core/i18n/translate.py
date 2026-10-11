"""Переводы backend по каталогам модулей (SYS-07-R13).

Каталог модуля — `app/modules/<module>/locales/<lang>.json` (вложенные объекты, ключи по схеме
SYS-07-R7). Ключ перевода — `<module>:<dotted.key>`, как полный ключ i18next. Интерполяция —
`{{name}}`; множественное число — суффиксы CLDR `_zero`, `_one`, `_two`, `_few`, `_many`,
`_other` по параметру `count` (SYS-07-R8). Недостающий ключ ищется по цепочке языков
(`ar` → `en` → `ru`, `en` → `ru`, как `fallbackLng` фронтенда); если его нет нигде,
возвращается сам ключ и пишется предупреждение.

Каталоги — неизменяемые файлы образа: они читаются при каждом вызове и в памяти процесса
не кэшируются (SYS-05-R1, R2).
"""

import json
import re
from pathlib import Path
from typing import Any

from babel import Locale

from app.core.i18n.format import babel_locale
from app.core.i18n.languages import UI_LANGUAGE_INFO
from app.core.logging.context import app_logger


DEFAULT_MODULES_ROOT = Path(__file__).resolve().parents[2] / "modules"
_KEY_PATTERN = re.compile(r"^(?P<module>[a-z][a-z0-9_]*):(?P<path>[a-z0-9_\-]+(\.[a-z0-9_\-]+)*)$")
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class Translator:
    """Переводчик по каталогам модулей в каталоге `root` (`app/modules`).

    Args:
        root: каталог, внутри которого лежат `<module>/locales/<lang>.json`.
    """

    def __init__(self, root: Path = DEFAULT_MODULES_ROOT) -> None:
        """Запоминает корень каталогов модулей."""
        self._root = root

    def _catalog(self, module: str, lang: str) -> dict[str, Any]:
        """Каталог модуля на языке `lang` (пустой, если файла нет)."""
        path = self._root / module / "locales" / f"{lang}.json"
        if not path.is_file():
            return {}
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    @staticmethod
    def _lookup(catalog: dict[str, Any], path: str) -> str | None:
        """Строка по пути `a.b.c` во вложенном каталоге."""
        node: Any = catalog
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node if isinstance(node, str) else None

    @staticmethod
    def _plural_category(lang: str, count: Any) -> str:
        """Категория CLDR для числа `count` на языке `lang`."""
        return str(Locale.parse(babel_locale(lang)).plural_form(count))

    def translate(self, key: str, lang: str, **params: Any) -> str:
        """Перевод ключа `<module>:<dotted.key>` на язык `lang` с подстановкой параметров.

        Args:
            key: полный ключ перевода.
            lang: язык интерфейса получателя (`ru`, `en`, `ar`).
            **params: значения для `{{name}}`; `count` выбирает форму множественного числа.

        Returns:
            Переведённая строка или сам ключ, если перевода нет ни на одном языке цепочки.

        Raises:
            ValueError: ключ не в формате `<module>:<dotted.key>` или язык не поддерживается.
        """
        match = _KEY_PATTERN.fullmatch(key)
        if match is None:
            raise ValueError(f"Translation key must be '<module>:<dotted.key>', got {key!r}")
        babel_locale(lang)
        module, path = match.group("module"), match.group("path")
        for candidate_lang in (lang, *UI_LANGUAGE_INFO[lang].fallbacks):
            catalog = self._catalog(module, candidate_lang)
            text = None
            if "count" in params:
                category = self._plural_category(candidate_lang, params["count"])
                text = self._lookup(catalog, f"{path}_{category}")
            text = text or self._lookup(catalog, path)
            if text is not None:
                return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)
        app_logger.warning("core.translation_missing", key=key, lang=lang)
        return key


def translate(key: str, lang: str, **params: Any) -> str:
    """Перевод ключа по каталогам модулей `app/modules/<module>/locales` (см. `Translator.translate`)."""
    return Translator().translate(key, lang, **params)
