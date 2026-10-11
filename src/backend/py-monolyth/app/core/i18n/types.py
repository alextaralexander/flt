"""Pydantic-тип кода языка BCP-47 в канонической форме (SYS-07-R25).

Проверка по реестру языков появится с модулем `languages` (этап 4); до этого тип проверяет
только каноническую форму тега.
"""

import re
from typing import Annotated, Final

from pydantic import StringConstraints


LANGUAGE_CODE_PATTERN: Final = r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$"
_LANGUAGE_CODE_RE: Final = re.compile(LANGUAGE_CODE_PATTERN)

LanguageCode = Annotated[str, StringConstraints(pattern=LANGUAGE_CODE_PATTERN)]


def is_language_code(value: str) -> bool:
    """Соответствует ли строка канонической форме BCP-47 (`en`, `zh-Hans`, `pt-BR`, `sr-Cyrl`)."""
    return bool(_LANGUAGE_CODE_RE.fullmatch(value))
