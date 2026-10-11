"""Ограничение размера тела запроса (SYS-03-R26).

Тело больше `HTTP_MAX_JSON_BODY_BYTES` отклоняется ответом `413 core.payload_too_large` в конверте
`ErrorResponseV1`: по заголовку `Content-Length` — до вызова обработчика, без него (chunked) —
по мере чтения тела. Файлы через `/api/*` не передаются (ADR-007), поэтому лимит общий для всех
операций; исключения для `multipart/form-data` появятся вместе с такими операциями (SYS-03, раздел 6).
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.http.errors import PayloadTooLargeError
from app.core.http.exception_handlers import domain_error_response
from configs.settings import settings


class _BodyTooLargeError(Exception):
    """Тело превысило лимит во время чтения."""


class BodyLimitMiddleware:
    """ASGI-middleware: отклоняет запросы с телом больше `HTTP_MAX_JSON_BODY_BYTES`."""

    def __init__(self, app: ASGIApp) -> None:
        """Оборачивает приложение; лимит читается из настроек на каждом запросе."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Проверяет `Content-Length` и считает байты тела при чтении."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = settings.HTTP_MAX_JSON_BODY_BYTES
        content_length = dict(scope["headers"]).get(b"content-length")
        if content_length is not None and content_length.isdigit() and int(content_length) > limit:
            await self._reject(scope, receive, send, limit)
            return

        received = 0
        exceeded = False
        replaced = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            # FastAPI превращает ошибку чтения тела в 400 — после превышения лимита
            # такой ответ подменяется на 413 (ответ ещё не начат, тело не отправлено).
            nonlocal replaced
            if replaced:
                return
            if exceeded and message["type"] == "http.response.start":
                replaced = True
                await self._reject(scope, receive, send, limit)
                return
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLargeError:
            if not replaced:
                await self._reject(scope, receive, send, limit)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        """Ответ 413 в конверте ошибок."""
        response = domain_error_response(PayloadTooLargeError(max_bytes=limit))
        await response(scope, receive, send)
