"""Контекст HTTP-запроса: `X-Request-ID`, локаль и пользователь (SYS-03-R20, R30).

`RequestContextMiddleware` (чистый ASGI) стоит снаружи logging-middleware:
- берёт `X-Request-ID` от HAProxy или генерирует UUID v7 (запуск без HAProxy на local и в pytest),
  кладёт его в `request.state.request_id` и в contextvar `current_request_id()`;
- добавляет к каждому ответу заголовки `X-Request-ID` и `Content-Language`
  (локаль, которую определила зависимость `RequestLanguage`, иначе — cookie → `Accept-Language` → `ru`).
`X-Instance-Id` добавляет `InstanceIdMiddleware` (`instance_header.py`, SYS-05-R5).

Состояние живёт только в `scope["state"]` и contextvar текущего запроса, между запросами
ничего не хранится.
"""

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from starlette.datastructures import MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.i18n.languages import UI_LANGUAGE_COOKIE
from app.core.i18n.request_language import RequestLanguage, request_language
from app.core.ids import new_id
from configs.stands import instance_id


REQUEST_ID_HEADER = "X-Request-ID"
# Допустимый внешний ID запроса: печатные символы без пробелов, до 128 знаков (иначе — новый UUID).
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

_current_request_id: ContextVar[str | None] = ContextVar("flt_request_id", default=None)


def current_request_id() -> str | None:
    """ID текущего HTTP-запроса (или `None` вне запроса)."""
    return _current_request_id.get()


def _header(scope: Scope, name: bytes) -> str | None:
    """Значение заголовка запроса из ASGI-scope (первое вхождение)."""
    for key, value in scope.get("headers", []):
        if key == name:
            return str(value.decode("latin-1"))
    return None


def _fallback_locale(scope: Scope) -> str:
    """Локаль без профиля пользователя: cookie `flt_ui_language` → `Accept-Language` → `ru`."""
    cookies = cookie_parser(_header(scope, b"cookie") or "")
    return request_language(
        profile_language=None,
        cookie_language=cookies.get(UI_LANGUAGE_COOKIE),
        accept_language=_header(scope, b"accept-language"),
    )


class RequestContextMiddleware:
    """ASGI-middleware: ID запроса и `Content-Language` для HTTP-ответов."""

    def __init__(self, app: ASGIApp) -> None:
        """Оборачивает ASGI-приложение."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Выставляет ID запроса до обработки и заголовки контекста в ответе."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, b"x-request-id")
        request_id = incoming if incoming and _REQUEST_ID_PATTERN.fullmatch(incoming) else str(new_id())
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = _current_request_id.set(request_id)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers.setdefault("Content-Language", state.get("locale") or _fallback_locale(scope))
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            _current_request_id.reset(token)


def set_request_user(request: Request, user: Any) -> None:
    """Сохраняет аутентифицированного пользователя в состоянии запроса.

    Вызывается слоем аутентификации shared kernel (`auth_user`, `auth_user_optional`);
    из состояния пользователя читают `RequestContext`, `RequestLanguage` (атрибут
    `ui_language`, если он есть) и `Idempotent()` (атрибут `user_id`).
    """
    request.state.user = user


def get_request_user(request: Request) -> Any:
    """Пользователь текущего запроса или `None`, если запрос анонимный."""
    return getattr(request.state, "user", None)


@dataclass(frozen=True)
class RequestContext:
    """Контекст запроса для логов и локализуемого содержимого (SYS-03-R20, R30).

    Attributes:
        request_id: ID запроса (`X-Request-ID`).
        instance_id: ID инстанса, обработавшего запрос.
        locale: язык интерфейса запроса (`ru`, `en`, `ar`).
        user: аутентифицированный пользователь или `None`.
    """

    request_id: str
    instance_id: str
    locale: str
    user: Any


async def get_request_context(request: Request, locale: RequestLanguage) -> RequestContext:
    """FastAPI-зависимость: контекст текущего запроса."""
    request_id = getattr(request.state, "request_id", None) or current_request_id() or str(new_id())
    return RequestContext(
        request_id=request_id,
        instance_id=instance_id(),
        locale=locale,
        user=get_request_user(request),
    )


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]
