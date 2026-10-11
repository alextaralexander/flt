"""Эндпоинт `/ws` роли `api`: handshake, цикл чтения, heartbeat, лимиты (SYS-04-R1…R3, R6, R8, R10, R11, R14).

Модули не объявляют WebSocket-маршрутов: каналы и команды подключаются через
`ModuleDefinition.ws_handlers` (SYS-04-R1). Соединения пользователя считаются глобально в Redis
(`shared_kernel:ws:conns:<user_id>`, TTL продлевает heartbeat); при недоступном Redis лимит
не применяется (fail-open: соединение важнее точности счётчика, ADR-003 раздел 3 п. 8).
"""

import asyncio
import json
import re
import time
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Security, WebSocket
from pydantic import ValidationError

from app.core.dao.caching import ModuleRedis
from app.core.dao.caching.module_redis import RedisUnavailableError
from app.core.logging.context import get_logger
from app.core.metrics.process_metrics import WS_CONNECTIONS, WS_MESSAGES
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_websocket
from app.core.ws.connection import WsConnection
from app.core.ws.hub import WsHub
from app.core.ws.protocol import CHANNEL_PATTERN, WsCloseCode, WsConfig, WsEnvelope, utc_timestamp


logger = get_logger("flt.core.ws")

WS_PATH = "/ws"
CONNECTION_COUNTER_TTL = timedelta(seconds=60)
_CHANNEL_RE = re.compile(CHANNEL_PATTERN)


class ConnectionLimiter:
    """Глобальный счётчик соединений пользователя (SYS-04-R14)."""

    def __init__(self, redis: ModuleRedis, limit: int) -> None:
        """Счётчик в `shared_kernel:ws:conns:<user_id>` с лимитом `limit`."""
        self.redis = redis
        self.limit = limit

    async def acquire(self, user_id: object) -> bool:
        """Увеличивает счётчик; False — лимит превышен (счётчик возвращается назад)."""
        key = f"ws:conns:{user_id}"
        try:
            count = await self.redis.incr(key, ttl=CONNECTION_COUNTER_TTL)
            if count > self.limit:
                await self.redis.incr(key, ttl=CONNECTION_COUNTER_TTL, amount=-1)
                return False
        except RedisUnavailableError:
            return True
        return True

    async def refresh(self, user_id: object) -> None:
        """Продлевает TTL счётчика (heartbeat)."""
        try:
            await self.redis.expire(f"ws:conns:{user_id}", ttl=CONNECTION_COUNTER_TTL)
        except RedisUnavailableError:
            return

    async def release(self, user_id: object) -> None:
        """Уменьшает счётчик при закрытии соединения."""
        try:
            await self.redis.incr(f"ws:conns:{user_id}", ttl=CONNECTION_COUNTER_TTL, amount=-1)
        except RedisUnavailableError:
            return


class WsSession:
    """Обработка одного соединения: входящие сообщения и heartbeat."""

    def __init__(self, connection: WsConnection, hub: WsHub, limiter: ConnectionLimiter) -> None:
        """Сессия соединения."""
        self.connection = connection
        self.hub = hub
        self.limiter = limiter
        self.last_inbound = time.monotonic()
        self.invalid_in_row = 0

    async def heartbeat(self) -> None:
        """`ws.ping` каждые `ping_interval_seconds`; `1011 pong_timeout` без входящих за `pong_timeout_seconds`."""
        config = self.connection.config
        while not self.connection.closed:
            await asyncio.sleep(config.ping_interval_seconds)
            if time.monotonic() - self.last_inbound > config.pong_timeout_seconds:
                await self.connection.close(WsCloseCode.INTERNAL_ERROR, "pong_timeout")
                return
            await self.connection.send("ws.ping", {"server_ts": utc_timestamp()})
            await self.limiter.refresh(self.connection.user.user_id)

    async def read_loop(self) -> None:
        """Читает сообщения до закрытия соединения."""
        websocket = self.connection.websocket
        while not self.connection.closed:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                self.connection.closed = True
                return
            self.last_inbound = time.monotonic()
            WS_MESSAGES.labels(direction="in").inc()
            text = message.get("text")
            if text is None:
                await self.connection.send_error("ws.unknown_stream", "Binary frame for an unknown stream")
                continue
            if len(text.encode()) > self.connection.config.max_message_bytes:
                await self.connection.close(WsCloseCode.MESSAGE_TOO_BIG)
                return
            await self.handle_text(text)

    async def handle_text(self, text: str) -> None:
        """Разбор конверта и маршрутизация по типу (SYS-04-R3, R4)."""
        try:
            envelope = WsEnvelope.model_validate(json.loads(text))
        except ValueError, ValidationError:
            self.invalid_in_row += 1
            if self.invalid_in_row >= self.connection.config.invalid_envelope_limit:
                await self.connection.close(WsCloseCode.POLICY_VIOLATION)
                return
            await self.connection.send_error("ws.invalid_envelope", "Message does not match the envelope")
            return
        self.invalid_in_row = 0
        await self.dispatch(envelope)

    async def dispatch(self, envelope: WsEnvelope) -> None:
        """Типы `ws.*` — shared kernel, остальные — обработчику модуля по типу команды."""
        conn = self.connection
        match envelope.type:
            case "ws.ping":
                await conn.send(
                    "ws.pong",
                    {"server_ts": utc_timestamp(), "client_ts": envelope.payload.get("client_ts")},
                    correlation_id=envelope.correlation_id,
                )
            case "ws.pong":
                return
            case "ws.subscribe" | "ws.unsubscribe":
                await self.subscription(envelope)
            case _:
                handler = self.hub.commands.get(envelope.type)
                if handler is None:
                    await conn.send_error(
                        "ws.unknown_type", "Unknown message type", correlation_id=envelope.correlation_id
                    )
                    return
                if envelope.correlation_id is None:
                    await conn.send_error("ws.invalid_envelope", "Command requires correlation_id")
                    return
                await handler.on_command(conn, envelope)

    async def subscription(self, envelope: WsEnvelope) -> None:
        """`ws.subscribe` / `ws.unsubscribe` → `ws.ack` или `ws.error` (SYS-04-R6)."""
        conn = self.connection
        channel = envelope.payload.get("channel")
        if not isinstance(channel, str) or not _CHANNEL_RE.match(channel):
            await conn.send_error(
                "ws.invalid_channel", "Invalid channel name", correlation_id=envelope.correlation_id, channel=channel
            )
            return
        if envelope.type == "ws.unsubscribe":
            await self.hub.unsubscribe(conn, channel)
            await conn.send("ws.ack", {"op": "unsubscribe", "channel": channel}, correlation_id=envelope.correlation_id)
            return
        error = await self.hub.subscribe(conn, channel)
        if error is not None:
            await conn.send_error(
                error, "Subscription rejected", correlation_id=envelope.correlation_id, channel=channel
            )
            return
        await conn.send(
            "ws.ack",
            {"op": "subscribe", "channel": channel, "state_url": self.hub.state_url(channel)},
            correlation_id=envelope.correlation_id,
        )


def create_ws_router(hub: WsHub, config: WsConfig | None = None) -> APIRouter:
    """Роутер с эндпоинтом `/ws` поверх хаба инстанса."""
    resolved = config or WsConfig()
    limiter = ConnectionLimiter(ModuleRedis("shared_kernel"), resolved.max_connections_per_user)
    router = APIRouter()

    @router.websocket(WS_PATH)
    async def websocket_endpoint(
        websocket: WebSocket, user: Annotated[UserSecuritySchema, Security(auth_websocket())]
    ) -> None:
        """Соединение фронтенда: аутентификация при handshake, затем протокол SYS-04."""
        await websocket.accept()
        connection = WsConnection(websocket, user, resolved)
        if not await limiter.acquire(user.user_id):
            await connection.close(WsCloseCode.TOO_MANY_CONNECTIONS)
            return
        WS_CONNECTIONS.inc()
        session = WsSession(connection, hub, limiter)
        heartbeat = asyncio.create_task(session.heartbeat(), name=f"ws-heartbeat-{connection.connection_id}")
        try:
            await hub.attach(connection)
            await session.read_loop()
        except Exception:
            logger.exception("core.ws_connection_error")
            await connection.close(WsCloseCode.INTERNAL_ERROR)
        finally:
            heartbeat.cancel()
            await hub.detach(connection)
            await limiter.release(user.user_id)
            WS_CONNECTIONS.dec()

    return router
