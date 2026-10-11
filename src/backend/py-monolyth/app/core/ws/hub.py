"""Каналы `/ws` и доставка между инстансами через Redis pub/sub (SYS-04-R5…R8, R13; SYS-05-R24).

Инстанс держит таблицы «канал → локальные соединения» и «пользователь → локальные соединения»
(живые соединения существуют только в процессе, поэтому это не нарушает SYS-05-R1) и подписан
на `ws:channel:<channel>` при первой локальной подписке и на `ws:user:<user_id>` при первом
соединении пользователя. Публикация с любого инстанса и любой роли — `WsPublisher`; pub/sub
не хранит сообщения, после переподключения клиент читает состояние канала по REST (SYS-04-R12).
"""

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.dao.caching.redis_conn import get_redis_client
from app.core.logging.context import get_logger
from app.core.security.schemas import UserSecuritySchema
from app.core.ws.connection import WsConnection
from app.core.ws.protocol import WsCloseCode, WsEnvelope
from configs.stands import instance_id


logger = get_logger("flt.core.ws")

CHANNEL_PREFIX = "ws:channel:"
USER_PREFIX = "ws:user:"
INSTANCE_PREFIX = "ws:instance:"

RedisFactory = Callable[[], Awaitable[Redis]]


@runtime_checkable
class WsChannelHandler(Protocol):
    """Обработчик каналов модуля, регистрируется в `ModuleDefinition.ws_handlers` (SYS-04-R1, R7, R8).

    Attributes:
        channel: Базовое имя канала `<module>.<channel>` (суффикс `:<id>` — у конкретной сущности).
        command_types: Типы входящих команд модуля, которые принимает обработчик.
    """

    channel: str
    command_types: frozenset[str]

    async def can_subscribe(self, principal: UserSecuritySchema, channel: str) -> bool:
        """Право подписки на канал: permissions SYS-06 и принадлежность сущности суффикса."""
        ...

    def state_url(self, channel: str) -> str | None:
        """REST-путь текущего состояния канала (SYS-05-R25)."""
        ...

    async def on_command(self, connection: WsConnection, envelope: WsEnvelope) -> None:
        """Команда модуля; `payload` валидирует сам модуль."""
        ...


def base_channel(channel: str) -> str:
    """Имя канала без суффикса сущности: `lessons.lesson:42` → `lessons.lesson`."""
    return channel.split(":", 1)[0]


def _redis_message(type_: str, payload: dict[str, Any], correlation_id: UUID | str | None) -> str:
    """Сообщение pub/sub: конверт без `seq`, `ts` и `channel` — их ставит инстанс соединения."""
    return json.dumps(
        {
            "type": type_,
            "correlation_id": str(correlation_id) if correlation_id is not None else None,
            "payload": payload,
        },
        separators=(",", ":"),
    )


class WsPublisher:
    """Публикация событий в каналы и адресно пользователю с любого инстанса и роли (SYS-04-R13).

    Attributes:
        redis_factory: Источник клиента Redis (по умолчанию — общий клиент процесса).
    """

    def __init__(self, redis_factory: RedisFactory = get_redis_client) -> None:
        """Сохраняет источник клиента."""
        self.redis_factory = redis_factory

    async def publish(
        self, channel: str, type_: str, payload: dict[str, Any], *, correlation_id: UUID | str | None = None
    ) -> int:
        """`PUBLISH ws:channel:<channel>`; возвращает число инстансов-получателей."""
        client = await self.redis_factory()
        return int(await client.publish(CHANNEL_PREFIX + channel, _redis_message(type_, payload, correlation_id)))

    async def publish_to_user(
        self, user_id: UUID, type_: str, payload: dict[str, Any], *, correlation_id: UUID | str | None = None
    ) -> int:
        """`PUBLISH ws:user:<user_id>`: во все соединения пользователя без подписки, `channel: null`."""
        client = await self.redis_factory()
        message = _redis_message(type_, payload, correlation_id)
        return int(await client.publish(f"{USER_PREFIX}{user_id}", message))


class WsHub:
    """Каналы и пользователи соединений инстанса, слушатель Redis pub/sub.

    Attributes:
        handlers: Обработчик модуля по базовому имени канала.
        commands: Обработчик модуля по типу входящей команды.
    """

    def __init__(self, handlers: Sequence[WsChannelHandler] = (), redis_factory: RedisFactory | None = None) -> None:
        """Регистрирует обработчики модулей; Redis подключается в `start`."""
        self.handlers: dict[str, WsChannelHandler] = {handler.channel: handler for handler in handlers}
        self.commands: dict[str, WsChannelHandler] = {
            command: handler for handler in handlers for command in handler.command_types
        }
        self._redis_factory = redis_factory or get_redis_client
        self._channels: dict[str, set[WsConnection]] = {}
        self._users: dict[UUID, set[WsConnection]] = {}
        self._pubsub: PubSub | None = None
        self._listener: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Подключает pub/sub и запускает слушатель (канал инстанса держит соединение pub/sub открытым)."""
        if self._pubsub is not None:
            return
        client = await self._redis_factory()
        self._pubsub = client.pubsub()
        await self._pubsub.subscribe(INSTANCE_PREFIX + instance_id())
        self._listener = asyncio.create_task(self._listen(self._pubsub), name="ws-hub-listener")

    async def stop(self) -> None:
        """Закрывает соединения кодом `1012 instance_shutdown` и останавливает слушатель (SYS-04-R18)."""
        connections = {conn for conns in self._users.values() for conn in conns}
        await asyncio.gather(*(conn.close(WsCloseCode.INSTANCE_SHUTDOWN) for conn in connections))
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()  # type: ignore[no-untyped-call]
        self._listener = None
        self._pubsub = None

    async def attach(self, connection: WsConnection) -> None:
        """Соединение пользователя: подписка инстанса на `ws:user:<user_id>` при первом соединении."""
        await self._ensure_started()
        async with self._lock:
            conns = self._users.setdefault(connection.user.user_id, set())
            if not conns and self._pubsub is not None:
                await self._pubsub.subscribe(f"{USER_PREFIX}{connection.user.user_id}")
            conns.add(connection)

    async def detach(self, connection: WsConnection) -> None:
        """Снимает подписки соединения и отписывает инстанс от опустевших каналов Redis."""
        for channel in list(connection.subscriptions):
            await self.unsubscribe(connection, channel)
        async with self._lock:
            conns = self._users.get(connection.user.user_id, set())
            conns.discard(connection)
            if not conns:
                self._users.pop(connection.user.user_id, None)
                if self._pubsub is not None:
                    with contextlib.suppress(Exception):
                        await self._pubsub.unsubscribe(f"{USER_PREFIX}{connection.user.user_id}")

    async def subscribe(self, connection: WsConnection, channel: str) -> str | None:
        """Подписка после проверки права обработчиком модуля-владельца (SYS-04-R6, R7).

        Returns:
            Код ошибки `ws.*` или None при успехе (повторная подписка — успех без побочных эффектов).
        """
        handler = self.handlers.get(base_channel(channel))
        if handler is None:
            return "ws.unknown_channel"
        if channel in connection.subscriptions:
            return None
        if len(connection.subscriptions) >= connection.config.max_subscriptions_per_connection:
            return "ws.subscription_limit"
        if not await handler.can_subscribe(connection.user, channel):
            return "ws.forbidden"
        await self._ensure_started()
        async with self._lock:
            conns = self._channels.setdefault(channel, set())
            if not conns and self._pubsub is not None:
                await self._pubsub.subscribe(CHANNEL_PREFIX + channel)
            conns.add(connection)
            connection.subscriptions.add(channel)
        return None

    async def unsubscribe(self, connection: WsConnection, channel: str) -> None:
        """Отписка соединения; при последней локальной подписке — `UNSUBSCRIBE` канала Redis."""
        async with self._lock:
            connection.subscriptions.discard(channel)
            conns = self._channels.get(channel)
            if conns is None:
                return
            conns.discard(connection)
            if not conns:
                del self._channels[channel]
                if self._pubsub is not None:
                    with contextlib.suppress(Exception):
                        await self._pubsub.unsubscribe(CHANNEL_PREFIX + channel)

    def state_url(self, channel: str) -> str | None:
        """REST-путь состояния канала от обработчика-владельца."""
        handler = self.handlers.get(base_channel(channel))
        return handler.state_url(channel) if handler is not None else None

    async def _ensure_started(self) -> None:
        """Ленивый старт (например, в тестах без lifespan)."""
        if self._pubsub is None:
            await self.start()

    async def _listen(self, pubsub: PubSub) -> None:
        """Цикл доставки сообщений Redis локальным соединениям."""
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                await self._deliver(_as_text(message["channel"]), _as_text(message["data"]))
            except Exception:
                logger.exception("core.ws_delivery_error")

    async def _deliver(self, redis_channel: str, data: str) -> None:
        """Рассылает сообщение pub/sub соединениям канала или пользователя."""
        body = json.loads(data)
        channel: str | None = None
        if redis_channel.startswith(CHANNEL_PREFIX):
            channel = redis_channel.removeprefix(CHANNEL_PREFIX)
            targets = set(self._channels.get(channel, ()))
        elif redis_channel.startswith(USER_PREFIX):
            targets = set(self._users.get(UUID(redis_channel.removeprefix(USER_PREFIX)), ()))
        else:
            return
        await asyncio.gather(
            *(
                conn.send(body["type"], body["payload"], channel=channel, correlation_id=body["correlation_id"])
                for conn in targets
            ),
            return_exceptions=True,
        )


def _as_text(value: str | bytes) -> str:
    """Строка из ответа redis-py (клиент может вернуть bytes)."""
    return value.decode() if isinstance(value, bytes) else value
