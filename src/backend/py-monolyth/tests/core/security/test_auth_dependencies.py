"""Тесты зависимостей аутентификации HTTP и WebSocket (ADR-006, раздел 3.4; SYS-03-R21; SYS-04-R2; SYS-06-R5).

Приложение собирается `create_app([])` (конверт ошибок `ErrorResponseV1`); верификатор токенов и
провайдер ролей подменяются через контейнер shared kernel, Redis не нужен.
"""

import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Security, WebSocket
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.container import container
from app.core.security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    Grant,
    RolePermissionsProvider,
    Scope,
    TokenVerifier,
    UserFlags,
    UserSecuritySchema,
    access_declaration,
    auth_user,
    auth_user_optional,
    auth_websocket,
    issue_csrf_token,
    load_verification_keys,
    public,
)
from app.main import create_app
from configs.settings import settings
from tests.support.jwt_keys import SigningKeyPair
from tests.support.tokens import TEST_AUDIENCE, TEST_ISSUER, access_claims, issue_access_token


pytestmark = pytest.mark.no_db

READ = "probe_mod:items:read"
CREATE = "probe_mod:items:create"
GATED = "probe_mod:lessons:start"
PUBLIC_READ = "probe_mod:catalog:read"
CSRF_SECRET = settings.AUTH_CSRF_SECRET.get_secret_value()
ORIGIN = settings.APP_PUBLIC_URL


class FakeProvider:
    """Матрица теста: learner — READ (own), CREATE (any), GATED только с подтверждённым email; аноним — PUBLIC_READ."""

    async def grants_for(self, roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]:
        """Гранты по ролям и флагам."""
        if not roles:
            return frozenset({Grant(code=PUBLIC_READ, scope=Scope.ANY)})
        grants = {Grant(code=READ, scope=Scope.OWN), Grant(code=CREATE, scope=Scope.ANY)}
        if flags.email_verified:
            grants.add(Grant(code=GATED, scope=Scope.OWN))
        return frozenset(grants)

    async def denial_code(self, permission: str, roles: Sequence[str], flags: UserFlags) -> str | None:
        """Код доступа к обучению для GATED без подтверждённого email (SYS-06-R7)."""
        if permission == GATED and roles and not flags.email_verified:
            return "identity.email_not_verified"
        return None


def _build_app() -> FastAPI:
    """Приложение с защищёнными, необязательными и публичными роутами и WebSocket."""
    app = create_app([])

    @app.get("/probe/items")
    async def read_items(user: Annotated[UserSecuritySchema, Security(auth_user(READ))]) -> dict[str, Any]:
        """Защищённое чтение."""
        grant = user.grant(READ)
        assert grant is not None
        return {"user_id": str(user.user_id), "scope": grant.scope, "bound": grant.user_id == user.user_id}

    @app.post("/probe/items")
    async def create_item(user: Annotated[UserSecuritySchema, Security(auth_user(CREATE))]) -> dict[str, str]:
        """Защищённое изменение (CSRF для cookie-клиента)."""
        return {"user_id": str(user.user_id)}

    @app.get("/probe/lessons")
    async def start_lesson(user: Annotated[UserSecuritySchema, Security(auth_user(GATED))]) -> dict[str, str]:
        """Право с признаком L."""
        return {"user_id": str(user.user_id)}

    @app.get("/probe/catalog")
    async def catalog(
        user: Annotated[UserSecuritySchema | None, Security(auth_user_optional(PUBLIC_READ))],
    ) -> dict[str, str | None]:
        """Роут, допускающий анонима с правом из столбца «аноним»."""
        return {"user_id": str(user.user_id) if user else None}

    @app.get("/probe/optional-items")
    async def optional_items(
        user: Annotated[UserSecuritySchema | None, Security(auth_user_optional(READ))],
    ) -> dict[str, str | None]:
        """Необязательная аутентификация с правом, которого нет у анонима."""
        return {"user_id": str(user.user_id) if user else None}

    @app.get("/probe/public", dependencies=[public()])
    async def public_page() -> dict[str, bool]:
        """Публичный роут."""
        return {"ok": True}

    @app.websocket("/probe/ws")
    async def ws_endpoint(
        websocket: WebSocket, user: Annotated[UserSecuritySchema, Security(auth_websocket())]
    ) -> None:
        """Эндпоинт WebSocket: принимает соединение и отправляет идентичность."""
        await websocket.accept()
        await websocket.send_json({"user_id": str(user.user_id), "sid": str(user.sid)})
        await websocket.close()

    return app


@pytest.fixture
def verifier(jwt_signing_keys: SigningKeyPair) -> Iterator[TokenVerifier]:
    """Верификатор без проверки отзыва, подменённый в контейнере."""
    keys = load_verification_keys(json.dumps({jwt_signing_keys.kid: jwt_signing_keys.public_pem}), signing_keys_json="")
    instance = TokenVerifier(keys, issuer=TEST_ISSUER, audience=TEST_AUDIENCE, revocation=None)
    with container.override(TokenVerifier, instance):
        yield instance


@pytest.fixture
def provider() -> Iterator[FakeProvider]:
    """Провайдер ролей теста вместо реализации `identity`."""
    fake = FakeProvider()
    with container.override(RolePermissionsProvider, fake):
        yield fake


@pytest.fixture
async def client(verifier: TokenVerifier, provider: FakeProvider) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент приложения теста."""
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as http:
        yield http


def _token(pair: SigningKeyPair, *, user_id: UUID | None = None, sid: UUID | None = None, **claims: Any) -> str:
    """Access-токен тестовой пары."""
    return issue_access_token(pair, access_claims(user_id, sid, **claims))


def _error_code(response: Any) -> str:
    """Код ошибки из конверта `ErrorResponseV1`."""
    return str(response.json()["messages"]["ERROR"][0]["message_mnemo_code"])


@pytest.mark.req("SYS-03-R21")
class TestBearer:
    """`Authorization: Bearer` — для любых клиентов, без CSRF."""

    async def test_valid_token_and_bound_grant(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Валидный токен и право есть — 200; грант привязан к пользователю, область из матрицы."""
        # - Arrange -
        user_id = uuid4()

        # - Act -
        response = await client.get(
            "/probe/items", headers={"Authorization": f"Bearer {_token(jwt_signing_keys, user_id=user_id)}"}
        )

        # - Assert -
        assert response.status_code == 200
        assert response.json() == {"user_id": str(user_id), "scope": "own", "bound": True}

    async def test_post_without_csrf(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Изменяющий запрос с Bearer не требует CSRF-токена."""
        response = await client.post("/probe/items", headers={"Authorization": f"Bearer {_token(jwt_signing_keys)}"})
        assert response.status_code == 200

    async def test_bearer_wins_over_cookie(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Есть заголовок — cookie игнорируются (даже битые), CSRF не проверяется."""
        # - Arrange -
        user_id = uuid4()
        client.cookies.set(ACCESS_COOKIE, "garbage")

        # - Act -
        response = await client.post(
            "/probe/items", headers={"Authorization": f"Bearer {_token(jwt_signing_keys, user_id=user_id)}"}
        )

        # - Assert -
        assert response.json() == {"user_id": str(user_id)}

    @pytest.mark.parametrize("header", ["", "Bearer", "Basic dXNlcjpwYXNz", "Bearer not-a-jwt"])
    async def test_invalid_header_is_401(self, client: AsyncClient, header: str) -> None:
        """Пустой, чужой схемы или невалидный токен — 401 `core.unauthenticated`."""
        response = await client.get("/probe/items", headers={"Authorization": header})
        assert response.status_code == 401
        assert _error_code(response) == "core.unauthenticated"

    async def test_missing_credentials_is_401(self, client: AsyncClient) -> None:
        """Без токена — 401 `core.unauthenticated`."""
        response = await client.get("/probe/items")
        assert response.status_code == 401
        assert _error_code(response) == "core.unauthenticated"

    async def test_token_in_query_is_not_accepted(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Токен в query-string не принимается (попадает в логи HAProxy — ADR-006, раздел 2.4)."""
        token = _token(jwt_signing_keys)
        response = await client.get("/probe/items", params={"access_token": token, "token": token})
        assert response.status_code == 401

    @pytest.mark.req("SYS-06-R17")
    async def test_agent_token_is_401(self, client: AsyncClient) -> None:
        """Токен агента `flta_…` на REST — 401 (SYS-06-R17)."""
        response = await client.get("/probe/items", headers={"Authorization": "Bearer flta_" + "x" * 43})
        assert response.status_code == 401


@pytest.mark.req("SYS-03-R21")
class TestCookieAndCsrf:
    """Cookie `__Host-flt_access` — для браузера; изменяющие методы требуют `X-CSRF-Token`."""

    def _login(self, client: AsyncClient, pair: SigningKeyPair, sid: UUID) -> str:
        """Ставит cookie доступа и CSRF, как после входа; возвращает CSRF-токен."""
        csrf = issue_csrf_token(sid, CSRF_SECRET)
        client.cookies.set(ACCESS_COOKIE, _token(pair, sid=sid))
        client.cookies.set(CSRF_COOKIE, csrf)
        return csrf

    async def test_get_without_csrf(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Безопасный метод с cookie не требует CSRF-токена."""
        self._login(client, jwt_signing_keys, uuid4())
        assert (await client.get("/probe/items")).status_code == 200

    async def test_post_with_valid_csrf(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Заголовок равен cookie и подписан для сессии токена — 200."""
        csrf = self._login(client, jwt_signing_keys, uuid4())
        assert (await client.post("/probe/items", headers={CSRF_HEADER: csrf})).status_code == 200

    @pytest.mark.parametrize("case", ["missing", "mismatch", "other-session"])
    async def test_post_with_bad_csrf_is_403(
        self, client: AsyncClient, jwt_signing_keys: SigningKeyPair, case: str
    ) -> None:
        """Нет заголовка, он не равен cookie или подписан для другой сессии — 403 `identity.csrf_invalid`."""
        # - Arrange -
        csrf = self._login(client, jwt_signing_keys, uuid4())
        headers = {
            "missing": {},
            "mismatch": {CSRF_HEADER: issue_csrf_token(uuid4(), CSRF_SECRET)},
            "other-session": {CSRF_HEADER: csrf},
        }[case]
        if case == "other-session":
            foreign = issue_csrf_token(uuid4(), CSRF_SECRET)
            client.cookies.set(CSRF_COOKIE, foreign)
            headers = {CSRF_HEADER: foreign}

        # - Act -
        response = await client.post("/probe/items", headers=headers)

        # - Assert -
        assert response.status_code == 403
        assert _error_code(response) == "identity.csrf_invalid"

    async def test_invalid_cookie_is_401(self, client: AsyncClient) -> None:
        """Битая cookie доступа — 401."""
        client.cookies.set(ACCESS_COOKIE, "garbage")
        assert (await client.get("/probe/items")).status_code == 401


@pytest.mark.req("SYS-06-R5")
class TestPermissions:
    """Право объявляет каждый роут; права выводит провайдер ролей при каждом запросе."""

    async def test_missing_permission_is_403(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Аутентифицированный без права — 403 `core.forbidden` без перечня недостающих прав."""
        # - Act -
        response = await client.get(
            "/probe/items", headers={"Authorization": f"Bearer {_token(jwt_signing_keys, roles=[])}"}
        )

        # - Assert -
        assert response.status_code == 403
        assert _error_code(response) == "core.forbidden"
        assert READ not in response.text

    @pytest.mark.req("SYS-06-R7")
    async def test_provider_denial_code(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Провайдер уточняет код отказа для права с признаком L (`identity.email_not_verified`)."""
        # - Arrange -
        unverified = _token(jwt_signing_keys, email_verified=False)
        verified = _token(jwt_signing_keys)

        # - Act -
        denied = await client.get("/probe/lessons", headers={"Authorization": f"Bearer {unverified}"})
        allowed = await client.get("/probe/lessons", headers={"Authorization": f"Bearer {verified}"})

        # - Assert -
        assert denied.status_code == 403
        assert _error_code(denied) == "identity.email_not_verified"
        assert allowed.status_code == 200

    @pytest.mark.req("SYS-06-R4")
    async def test_without_provider_nobody_has_permissions(
        self, verifier: TokenVerifier, jwt_signing_keys: SigningKeyPair
    ) -> None:
        """Модуль `identity` не подключён — прав нет ни у кого (fail-closed)."""
        # - Arrange -
        assert not container.is_registered(RolePermissionsProvider)
        async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as http:
            # - Act -
            response = await http.get("/probe/items", headers={"Authorization": f"Bearer {_token(jwt_signing_keys)}"})

        # - Assert -
        assert response.status_code == 403

    def test_malformed_permission_is_rejected_at_declaration(self) -> None:
        """Код права не по формату SYS-06-R2 — ошибка при объявлении роута, а не в рантайме."""
        with pytest.raises(ValueError, match="SYS-06-R2"):
            auth_user("PROBE_READ")


@pytest.mark.req("SYS-06-R10")
class TestAnonymousAccess:
    """`auth_user_optional` и `public()` — для действий, разрешённых анониму."""

    async def test_anonymous_with_anonymous_grant(self, client: AsyncClient) -> None:
        """Аноним получает доступ к праву из столбца «аноним»."""
        response = await client.get("/probe/catalog")
        assert response.json() == {"user_id": None}

    async def test_authenticated_user_is_passed(self, client: AsyncClient, jwt_signing_keys: SigningKeyPair) -> None:
        """С токеном роут получает пользователя; без права у него — 403."""
        # - Arrange -
        user_id = uuid4()
        headers = {"Authorization": f"Bearer {_token(jwt_signing_keys, user_id=user_id)}"}

        # - Act -
        allowed = await client.get("/probe/optional-items", headers=headers)
        denied = await client.get("/probe/catalog", headers=headers)

        # - Assert -
        assert allowed.json() == {"user_id": str(user_id)}
        assert denied.status_code == 403

    async def test_anonymous_without_grant_is_401(self, client: AsyncClient) -> None:
        """Анониму без права из столбца «аноним» — 401 `core.unauthenticated`."""
        response = await client.get("/probe/optional-items")
        assert response.status_code == 401
        assert _error_code(response) == "core.unauthenticated"

    async def test_public_route(self, client: AsyncClient) -> None:
        """Роут с `public()` доступен без аутентификации."""
        assert (await client.get("/probe/public")).json() == {"ok": True}

    def test_access_is_introspectable(self) -> None:
        """Объявление доступа читается из зависимостей роута (для `test_every_route_declares_access`)."""
        # - Arrange -
        app = _build_app()
        routes = {
            route.path: route for route in app.routes if isinstance(route, APIRoute) and "GET" in (route.methods or ())
        }

        # - Act -
        def declarations(path: str) -> list[tuple[str, str | None]]:
            found: list[tuple[str, str | None]] = []
            stack = list(routes[path].dependant.dependencies)
            while stack:
                dependency = stack.pop()
                declaration = access_declaration(dependency.call)
                if declaration is not None:
                    found.append((declaration.kind, declaration.permission))
                stack.extend(dependency.dependencies)
            return found

        # - Assert -
        assert declarations("/probe/items") == [("user", READ)]
        assert declarations("/probe/catalog") == [("optional", PUBLIC_READ)]
        assert declarations("/probe/public") == [("public", None)]


@pytest.mark.req("SYS-04-R2")
class TestWebSocketHandshake:
    """Аутентификация `/ws` при handshake: Bearer или cookie с проверкой `Origin`; отказ — закрытие 4401."""

    @pytest.fixture
    def ws_client(self, verifier: TokenVerifier, provider: FakeProvider) -> Iterator[TestClient]:
        """Синхронный клиент Starlette для WebSocket."""
        with TestClient(_build_app()) as test_client:
            yield test_client

    def test_bearer(self, ws_client: TestClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Bearer при handshake — соединение принято, идентичность зафиксирована."""
        # - Arrange -
        user_id, sid = uuid4(), uuid4()
        headers = {"Authorization": f"Bearer {_token(jwt_signing_keys, user_id=user_id, sid=sid)}"}

        # - Act -
        with ws_client.websocket_connect("/probe/ws", headers=headers) as ws:
            message = ws.receive_json()

        # - Assert -
        assert message == {"user_id": str(user_id), "sid": str(sid)}

    def test_cookie_with_matching_origin(self, ws_client: TestClient, jwt_signing_keys: SigningKeyPair) -> None:
        """Cookie и `Origin` = `APP_PUBLIC_URL` — соединение принято."""
        ws_client.cookies.set(ACCESS_COOKIE, _token(jwt_signing_keys))
        with ws_client.websocket_connect("/probe/ws", headers={"Origin": ORIGIN}) as ws:
            assert "user_id" in ws.receive_json()

    @pytest.mark.req("SYS-04-R10")
    @pytest.mark.parametrize("case", ["no-credentials", "cookie-no-origin", "cookie-foreign-origin", "query", "agent"])
    def test_rejected_handshake_closes_4401(
        self, ws_client: TestClient, jwt_signing_keys: SigningKeyPair, case: str
    ) -> None:
        """Нет учётных данных, cookie без `Origin` или с чужим, токен в query, токен агента — закрытие 4401."""
        # - Arrange -
        token = _token(jwt_signing_keys)
        url, headers = "/probe/ws", {}
        if case.startswith("cookie"):
            ws_client.cookies.set(ACCESS_COOKIE, token)
            if case == "cookie-foreign-origin":
                headers = {"Origin": "https://evil.example"}
        elif case == "query":
            url = f"/probe/ws?access_token={token}"
        elif case == "agent":
            headers = {"Authorization": "Bearer flta_" + "x" * 43}

        # - Act -
        with pytest.raises(WebSocketDisconnect) as exc_info, ws_client.websocket_connect(url, headers=headers) as ws:
            ws.receive_json()

        # - Assert -
        assert exc_info.value.code == 4401
        assert exc_info.value.reason == "unauthenticated"
