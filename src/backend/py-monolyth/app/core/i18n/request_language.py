"""Язык запроса: профиль → cookie `flt_ui_language` → `Accept-Language` → `ru` (SYS-07-R3, SYS-03-R30).

Язык профиля берётся из атрибута `ui_language` пользователя, которого слой аутентификации
кладёт в `request.state.user` (`app.core.http.context.set_request_user`). Cookie читается
через параметр FastAPI `Cookie`, backend её не устанавливает (SYS-07-R6). Выбранная локаль
сохраняется в `request.state.locale` и возвращается клиенту заголовком `Content-Language`.
"""

from collections.abc import Sequence
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request

from app.core.i18n.languages import DEFAULT_UI_LANGUAGE, UI_LANGUAGE_COOKIE, UI_LANGUAGES, is_ui_language


def pick_from_accept_language(
    header: str | None,
    supported: Sequence[str] = UI_LANGUAGES,
    default: str = DEFAULT_UI_LANGUAGE,
) -> str:
    """Выбирает язык из заголовка `Accept-Language` по RFC 9110.

    Диапазоны сортируются по убыванию q-веса (при равных весах — по порядку в заголовке);
    берётся первый, чей первичный субтег поддерживается (`ar-EG` → `ar`). Диапазоны с `q=0`
    и `*` пропускаются; некорректные веса считаются нулевыми.

    Args:
        header: значение заголовка или `None`.
        supported: поддерживаемые языки.
        default: язык, если подходящего нет.

    Returns:
        Код поддерживаемого языка.
    """
    if not header:
        return default
    ranges: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        pieces = [piece.strip() for piece in part.split(";")]
        tag = pieces[0].lower()
        weight = 1.0
        for parameter in pieces[1:]:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        if tag and tag != "*" and weight > 0:
            ranges.append((-weight, index, tag))
    for _, _, tag in sorted(ranges):
        primary = tag.split("-", 1)[0]
        if primary in supported:
            return primary
    return default


def request_language(
    *,
    profile_language: str | None,
    cookie_language: str | None,
    accept_language: str | None,
) -> str:
    """Определяет язык интерфейса по источникам в порядке приоритета SYS-07-R3.

    Значения профиля и cookie вне `UI_LANGUAGES` пропускаются.
    """
    if is_ui_language(profile_language):
        return str(profile_language)
    if is_ui_language(cookie_language):
        return str(cookie_language)
    return pick_from_accept_language(accept_language)


async def resolve_request_language(
    request: Request,
    flt_ui_language: Annotated[str | None, Cookie(alias=UI_LANGUAGE_COOKIE, include_in_schema=False)] = None,
    accept_language: Annotated[str | None, Header(alias="Accept-Language", include_in_schema=False)] = None,
) -> str:
    """FastAPI-зависимость: язык запроса; сохраняет его в `request.state.locale`."""
    user = getattr(request.state, "user", None)
    locale = request_language(
        profile_language=getattr(user, "ui_language", None),
        cookie_language=flt_ui_language,
        accept_language=accept_language,
    )
    request.state.locale = locale
    return locale


RequestLanguage = Annotated[str, Depends(resolve_request_language)]
