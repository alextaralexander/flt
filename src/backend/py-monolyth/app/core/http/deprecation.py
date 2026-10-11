"""Вывод операций из эксплуатации: заголовки `Deprecation`, `Sunset`, `Link` (SYS-03-R28).

Декоратор `@deprecated(since=..., sunset=..., successor=...)` помечает обработчик роута;
`DeprecationMiddleware` после маршрутизации читает пометку из `scope["endpoint"]` и добавляет
заголовки: `Deprecation: @<unix-время решения>` (RFC 9745), `Sunset: <HTTP-date>` (RFC 8594)
и, если есть замена, `Link: <путь>; rel="successor-version"`. Пометка — неизменяемый атрибут
функции, задаётся при объявлении роута (состояния процесса не добавляет).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from email.utils import format_datetime
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


MIN_SUNSET_DAYS = 90
_ATTRIBUTE = "__flt_deprecation__"


@dataclass(frozen=True)
class Deprecation:
    """Сведения о выводе операции.

    Attributes:
        since: Дата решения о выводе.
        sunset: Дата удаления операции.
        successor: Путь операции-замены или None.
    """

    since: date
    sunset: date
    successor: str | None = None

    def headers(self) -> dict[str, str]:
        """Заголовки ответа устаревшей операции."""
        since_ts = int(datetime.combine(self.since, time(), tzinfo=UTC).timestamp())
        values = {
            "Deprecation": f"@{since_ts}",
            "Sunset": format_datetime(datetime.combine(self.sunset, time(), tzinfo=UTC), usegmt=True),
        }
        if self.successor:
            values["Link"] = f'<{self.successor}>; rel="successor-version"'
        return values


def deprecated[F: Callable[..., Any]](*, since: date, sunset: date, successor: str | None = None) -> Callable[[F], F]:
    """Помечает обработчик роута как устаревший.

    Args:
        since: Дата решения о выводе (значение `Deprecation`).
        sunset: Дата удаления (значение `Sunset`), не раньше чем через 90 дней после `since`.
        successor: Путь операции-замены для заголовка `Link`.

    Raises:
        ValueError: Между `since` и `sunset` меньше 90 дней (при объявлении роута).
    """
    if (sunset - since).days < MIN_SUNSET_DAYS:
        raise ValueError(f"Sunset должен быть не раньше чем через {MIN_SUNSET_DAYS} дней после Deprecation.")
    info = Deprecation(since=since, sunset=sunset, successor=successor)

    def mark(endpoint: F) -> F:
        """Сохраняет сведения о выводе в атрибуте обработчика."""
        setattr(endpoint, _ATTRIBUTE, info)
        return endpoint

    return mark


class DeprecationMiddleware:
    """ASGI-middleware: заголовки вывода для обработчиков, помеченных `@deprecated`."""

    def __init__(self, app: ASGIApp) -> None:
        """Оборачивает приложение."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Добавляет заголовки в начало ответа, если маршрут указывает на устаревший обработчик."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                info = getattr(scope.get("endpoint"), _ATTRIBUTE, None)
                if isinstance(info, Deprecation):
                    headers = MutableHeaders(scope=message)
                    for name, value in info.headers().items():
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
