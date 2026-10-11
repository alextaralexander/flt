"""Протокол `/ws`: конверт сообщения, коды закрытия, параметры соединения (SYS-04-R3, R4, R10, R11, R14)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$"
CHANNEL_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(:[A-Za-z0-9_-]{1,64})?$"


class WsCloseCode(IntEnum):
    """Коды закрытия соединения по таблице SYS-04-R10; другие коды сервер не использует."""

    CLIENT_CLOSE = 1000
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    INTERNAL_ERROR = 1011
    INSTANCE_SHUTDOWN = 1012
    OUTBOX_OVERFLOW = 1013
    UNAUTHENTICATED = 4401
    AGENT_UPDATE_REQUIRED = 4426
    TOO_MANY_CONNECTIONS = 4429


# Причина закрытия по умолчанию (ASCII, до 123 байт).
CLOSE_REASONS: dict[WsCloseCode, str] = {
    WsCloseCode.CLIENT_CLOSE: "client_close",
    WsCloseCode.POLICY_VIOLATION: "policy_violation",
    WsCloseCode.MESSAGE_TOO_BIG: "message_too_big",
    WsCloseCode.INTERNAL_ERROR: "internal_error",
    WsCloseCode.INSTANCE_SHUTDOWN: "instance_shutdown",
    WsCloseCode.OUTBOX_OVERFLOW: "outbox_overflow",
    WsCloseCode.UNAUTHENTICATED: "unauthenticated",
    WsCloseCode.AGENT_UPDATE_REQUIRED: "agent_update_required",
    WsCloseCode.TOO_MANY_CONNECTIONS: "too_many_connections",
}


@dataclass(frozen=True)
class WsConfig:
    """Параметры соединений `/ws` (значения по умолчанию — SYS-04-R10, R11, R14).

    Attributes:
        ping_interval_seconds: Период `ws.ping` сервера.
        pong_timeout_seconds: Закрытие `1011 pong_timeout` без входящих сообщений за этот срок.
        max_connections_per_user: Лимит соединений пользователя на всех инстансах (`4429`).
        max_message_bytes: Лимит размера текстового сообщения (`1009`).
        max_subscriptions_per_connection: Лимит подписок на соединение (`ws.subscription_limit`).
        send_timeout_seconds: Срок отправки одного сообщения (`1011 send_timeout`).
        invalid_envelope_limit: Подряд идущие `ws.invalid_envelope` до закрытия `1008`.
    """

    ping_interval_seconds: float = 30.0
    pong_timeout_seconds: float = 60.0
    max_connections_per_user: int = 5
    max_message_bytes: int = 64 * 1024
    max_subscriptions_per_connection: int = 50
    send_timeout_seconds: float = 15.0
    invalid_envelope_limit: int = 3


class WsEnvelope(BaseModel):
    """Конверт текстового сообщения: ровно шесть полей (SYS-04-R3)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=TYPE_PATTERN, description="Тип `<namespace>.<event>` (SYS-04-R4).")
    correlation_id: UUID | None = Field(description="Корреляция команды, ответа и событий.")
    channel: str | None = Field(description="Канал `<module>.<channel>[:<id>]` или null.")
    seq: int = Field(ge=0, description="Порядковый номер сообщения отправителя в соединении.")
    ts: datetime = Field(description="Время отправителя, ISO 8601 UTC.")
    payload: dict[str, Any] = Field(description="Данные по схеме типа.")


def utc_timestamp() -> str:
    """Текущее время в формате конверта: ISO 8601 UTC с миллисекундами и `Z`."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
