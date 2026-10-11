"""Заголовок `X-Instance-Id` в каждом ответе инстанса (SYS-05-R5).

Тесты масштабируемости и smoke-тесты доказывают по нему, что шаги сценария выполнились на
разных инстансах роли `api`. Значение — `instance_id` из ADR-010 (`HOSTNAME` контейнера или пода).
Middleware чистый ASGI и стоит снаружи остальных, поэтому заголовок получают и ответы с ошибками
(включая 500 из logging-middleware), и ответ handshake WebSocket. На стендах без `FLT_EXPOSE_DOCS`
HAProxy снимает заголовок из ответов клиентам (ADR-012).
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from configs.stands import instance_id


INSTANCE_HEADER = "X-Instance-Id"
# Сообщения ASGI, начинающие ответ: HTTP, принятие WebSocket и отказ handshake с HTTP-ответом.
_RESPONSE_START_TYPES = frozenset({"http.response.start", "websocket.accept", "websocket.http.response.start"})


class InstanceIdMiddleware:
    """Добавляет `X-Instance-Id` к ответам HTTP и handshake WebSocket."""

    def __init__(self, app: ASGIApp, instance: str | None = None) -> None:
        """Оборачивает приложение; идентификатор инстанса вычисляется один раз (он неизменен в процессе).

        Args:
            app: Внутреннее ASGI-приложение.
            instance: Идентификатор инстанса; по умолчанию `instance_id()` (`HOSTNAME`).
        """
        self.app = app
        self._header = (INSTANCE_HEADER.lower().encode("latin-1"), (instance or instance_id()).encode("latin-1"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Пропускает запрос дальше, дописывая заголовок в начало ответа."""
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        async def send_with_instance(message: Message) -> None:
            if message["type"] in _RESPONSE_START_TYPES:
                message = {**message, "headers": [*message.get("headers", []), self._header]}
            await send(message)

        await self.app(scope, receive, send_with_instance)
