"""Фикстуры тестов `/ws`: верификатор токенов, провайдер ролей, обработчик канала-пробы, фабрика приложений."""

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from app.core.container import container
from app.core.security import Grant, RolePermissionsProvider, TokenVerifier, UserFlags, load_verification_keys
from app.core.security.schemas import UserSecuritySchema
from app.core.ws.connection import WsConnection
from app.core.ws.endpoint import create_ws_router
from app.core.ws.hub import WsHub
from app.core.ws.protocol import WsConfig, WsEnvelope
from configs.settings import settings
from tests.support.jwt_keys import SigningKeyPair
from tests.support.tokens import TEST_AUDIENCE, TEST_ISSUER, access_claims, issue_access_token


class ProbeHandler:
    """Каналы `probe_mod.room[:<id>]`: запрещён только `probe_mod.room:secret`; команда эха."""

    channel = "probe_mod.room"
    command_types = frozenset({"probe_mod.room.echo"})

    async def can_subscribe(self, principal: UserSecuritySchema, channel: str) -> bool:
        """Право подписки: всё, кроме `:secret`."""
        return not channel.endswith(":secret")

    def state_url(self, channel: str) -> str | None:
        """REST-путь состояния комнаты."""
        return f"/api/v1/probe-mod/rooms/{channel.split(':', 1)[-1]}"

    async def on_command(self, connection: WsConnection, envelope: WsEnvelope) -> None:
        """Эхо payload с тем же correlation_id."""
        await connection.send("probe_mod.room.echoed", envelope.payload, correlation_id=envelope.correlation_id)


class EmptyProvider:
    """Провайдер ролей без грантов."""

    async def grants_for(self, roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]:
        """Пустой набор грантов."""
        return frozenset()


@pytest.fixture(autouse=True)
def ws_security(jwt_signing_keys: SigningKeyPair) -> Iterator[None]:
    """Верификатор без проверки отзыва и пустой провайдер ролей в контейнере."""
    keys = load_verification_keys(json.dumps({jwt_signing_keys.kid: jwt_signing_keys.public_pem}), signing_keys_json="")
    verifier = TokenVerifier(keys, issuer=TEST_ISSUER, audience=TEST_AUDIENCE, revocation=None)
    with container.override(TokenVerifier, verifier), container.override(RolePermissionsProvider, EmptyProvider()):
        yield


@pytest.fixture
def bearer(jwt_signing_keys: SigningKeyPair) -> Callable[[UUID | None], dict[str, str]]:
    """Заголовок `Authorization` для пользователя (по умолчанию — нового)."""

    def make(user_id: UUID | None = None) -> dict[str, str]:
        token = issue_access_token(jwt_signing_keys, access_claims(user_id or uuid4()))
        return {"Authorization": f"Bearer {token}", "Origin": settings.APP_PUBLIC_URL}

    return make


@pytest.fixture
def ws_app() -> Callable[..., FastAPI]:
    """Приложение с `/ws` и обработчиком-пробой; каждое — как отдельный инстанс со своим хабом."""

    def make(config: WsConfig | None = None) -> FastAPI:
        app = FastAPI()
        hub = WsHub([ProbeHandler()])
        app.state.ws_hub = hub
        app.include_router(create_ws_router(hub, config))
        return app

    return make


def envelope(
    type_: str, payload: dict[str, Any] | None = None, *, seq: int = 0, correlation_id: str | None = None
) -> str:
    """Текст сообщения клиента."""
    return json.dumps(
        {
            "type": type_,
            "correlation_id": correlation_id or str(uuid4()),
            "channel": None,
            "seq": seq,
            "ts": "2026-10-11T00:00:00.000Z",
            "payload": payload or {},
        }
    )
