"""Соединение `/ws`: исходящий конверт с `seq`, отправка с таймаутом, закрытие кодом SYS-04-R10."""

import asyncio
import json
from typing import Any
from uuid import UUID

from starlette.websockets import WebSocket, WebSocketState

from app.core.ids import new_id
from app.core.metrics.process_metrics import WS_MESSAGES
from app.core.security.schemas import UserSecuritySchema
from app.core.ws.protocol import CLOSE_REASONS, WsCloseCode, WsConfig, utc_timestamp


class WsConnection:
    """Одно соединение пользователя на этом инстансе.

    Attributes:
        websocket: Соединение Starlette.
        user: Пользователь, аутентифицированный при handshake.
        config: Параметры соединения.
        connection_id: Идентификатор соединения (UUID v7).
        subscriptions: Каналы, на которые подписано соединение.
    """

    def __init__(self, websocket: WebSocket, user: UserSecuritySchema, config: WsConfig) -> None:
        """Создаёт соединение с нулевым счётчиком `seq`."""
        self.websocket = websocket
        self.user = user
        self.config = config
        self.connection_id: UUID = new_id()
        self.subscriptions: set[str] = set()
        self._seq = 0
        self._send_lock = asyncio.Lock()
        self.closed = False

    async def send(
        self,
        type_: str,
        payload: dict[str, Any] | None = None,
        *,
        channel: str | None = None,
        correlation_id: UUID | str | None = None,
    ) -> None:
        """Отправляет конверт; `seq` монотонен по всем исходящим сообщениям соединения.

        При превышении `send_timeout_seconds` соединение закрывается `1011 send_timeout`.
        """
        if self.closed:
            return
        async with self._send_lock:
            message = {
                "type": type_,
                "correlation_id": str(correlation_id) if correlation_id is not None else None,
                "channel": channel,
                "seq": self._seq,
                "ts": utc_timestamp(),
                "payload": payload or {},
            }
            self._seq += 1
            try:
                await asyncio.wait_for(
                    self.websocket.send_text(json.dumps(message, separators=(",", ":"))),
                    timeout=self.config.send_timeout_seconds,
                )
            except TimeoutError:
                await self.close(WsCloseCode.INTERNAL_ERROR, "send_timeout")
                return
        WS_MESSAGES.labels(direction="out").inc()

    async def send_error(
        self, code: str, message: str, *, correlation_id: UUID | str | None = None, **details: Any
    ) -> None:
        """`ws.error` с кодом ошибки протокола (SYS-04-R6, R8)."""
        await self.send("ws.error", {"code": code, "message": message, **details}, correlation_id=correlation_id)

    async def close(self, code: WsCloseCode, reason: str | None = None) -> None:
        """Закрывает соединение кодом из таблицы SYS-04-R10 (повторный вызов ничего не делает)."""
        if self.closed:
            return
        self.closed = True
        if self.websocket.application_state is WebSocketState.CONNECTED:
            await self.websocket.close(code=int(code), reason=reason or CLOSE_REASONS[code])
