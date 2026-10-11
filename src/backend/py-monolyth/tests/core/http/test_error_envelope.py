"""Контрактные тесты конверта ошибок `ErrorResponseV1` (SYS-03-R7, R8, R9, R22)."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from pydantic import BaseModel

from app.core.dao.caching import RedisUnavailableError
from app.core.exceptions import InsufficientPermissionsError, InvalidTokenError, ModelNotFoundInDatabaseError
from app.core.http.errors import DomainError, ForbiddenError, RateLimitedError
from app.core.http.schemas import ErrorResponseV1
from app.core.security.schemas import UserSecuritySchema
from configs.settings import settings


pytestmark = pytest.mark.no_db


class ProbeTakenError(DomainError):
    """Тестовая доменная ошибка модуля с параметром, скрываемым вне DEBUG_MODE."""

    code = "core_test.probe_taken"
    http_status = 409
    message = "Probe is already taken"
    hidden_details = ("owner_id",)


class SampleModel:
    """Класс-заглушка модели: обработчику 404 нужно только имя класса."""


class ProbeBody(BaseModel):
    """Тело тестового запроса."""

    title: str
    count: int


def _error(response: Response) -> dict[str, Any]:
    """Проверяет конверт по схеме и возвращает единственную ошибку."""
    assert response.headers["content-type"].startswith("application/json")
    envelope = ErrorResponseV1.model_validate(response.json())
    assert envelope.payload is None
    assert envelope.messages.INFO == envelope.messages.WARNING == []
    assert len(envelope.messages.ERROR) == 1
    assert envelope.request_id == response.headers["X-Request-ID"]
    return envelope.messages.ERROR[0].model_dump()


@pytest.fixture
def app_with_routes(http_app: FastAPI) -> FastAPI:
    """Приложение с тестовыми роутами, бросающими разные ошибки."""

    @http_app.get("/api/v1/core-test/domain")
    async def domain() -> None:
        raise ProbeTakenError(probe_id="p1", owner_id="u1")

    @http_app.post("/api/v1/core-test/validate")
    async def validate(body: ProbeBody) -> ProbeBody:
        return body

    @http_app.get("/api/v1/core-test/boom")
    async def boom() -> None:
        raise RuntimeError("unexpected")

    @http_app.get("/api/v1/core-test/redis")
    async def redis() -> None:
        raise RedisUnavailableError("down")

    @http_app.get("/api/v1/core-test/forbidden")
    async def forbidden() -> None:
        user = UserSecuritySchema(user_id="u1", permissions=set(), access_token="t")
        raise InsufficientPermissionsError(user, ["core_test:probe:read"])

    @http_app.get("/api/v1/core-test/forbidden-new")
    async def forbidden_new() -> None:
        raise ForbiddenError(missing_permissions=["core_test:probe:read"])

    @http_app.get("/api/v1/core-test/token")
    async def token() -> None:
        raise InvalidTokenError("invalid-token-value")

    @http_app.get("/api/v1/core-test/missing")
    async def missing() -> None:
        raise ModelNotFoundInDatabaseError(model_id="m1", model=SampleModel, is_deleted=True)

    @http_app.get("/api/v1/core-test/limited")
    async def limited() -> None:
        raise RateLimitedError(scope="probe", retry_after=timedelta(milliseconds=1500))

    return http_app


@pytest.mark.req("SYS-03-R7")
@pytest.mark.req("SYS-03-R8")
async def test_domain_error_envelope(
    app_with_routes: FastAPI, http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Доменная ошибка модуля: статус, код и детали из класса; `hidden_details` скрыты вне DEBUG_MODE."""
    # - Arrange -
    monkeypatch.setattr(settings, "DEBUG_MODE", False)

    # - Act -
    response = await http_client.get("/api/v1/core-test/domain")

    # - Assert -
    error = _error(response)
    assert response.status_code == 409
    assert error == {
        "code": "core_test.probe_taken",
        "message": "Probe is already taken",
        "details": {"probe_id": "p1"},
    }


@pytest.mark.req("SYS-03-R7")
async def test_hidden_details_shown_in_debug(
    app_with_routes: FastAPI, http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """В DEBUG_MODE скрываемые детали отдаются для отладки."""
    monkeypatch.setattr(settings, "DEBUG_MODE", True)
    response = await http_client.get("/api/v1/core-test/domain")
    assert _error(response)["details"] == {"probe_id": "p1", "owner_id": "u1"}


@pytest.mark.req("SYS-03-R7")
@pytest.mark.req("SYS-03-R8")
async def test_not_found_route_and_method(app_with_routes: FastAPI, http_client: AsyncClient) -> None:
    """404 несуществующего маршрута — `core.not_found`; 405 — `core.method_not_allowed`."""
    # - Act -
    not_found = await http_client.get("/api/v1/core-test/does-not-exist")
    not_allowed = await http_client.delete("/api/v1/core-test/domain")

    # - Assert -
    assert not_found.status_code == 404
    assert _error(not_found)["code"] == "core.not_found"
    assert not_allowed.status_code == 405
    assert _error(not_allowed)["code"] == "core.method_not_allowed"


@pytest.mark.req("SYS-03-R9")
async def test_validation_error_shape(app_with_routes: FastAPI, http_client: AsyncClient) -> None:
    """422 `core.validation_failed`: `details.errors` — элементы `{loc, type, msg, ctx}` без входных данных."""
    # - Act -
    response = await http_client.post("/api/v1/core-test/validate", json={"title": "x", "count": "many"})
    broken = await http_client.post(
        "/api/v1/core-test/validate", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    # - Assert -
    error = _error(response)
    assert response.status_code == 422
    assert error["code"] == "core.validation_failed"
    assert error["details"]["errors"] == [
        {
            "loc": ["body", "count"],
            "type": "int_parsing",
            "msg": "Input should be a valid integer, unable to parse string as an integer",
            "ctx": {},
        }
    ]
    assert broken.status_code == 422
    assert _error(broken)["code"] == "core.validation_failed"


@pytest.mark.req("SYS-03-R7")
@pytest.mark.req("SYS-03-R8")
async def test_unhandled_exception_is_internal(
    app_with_routes: FastAPI, http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Необработанное исключение — `500 core.internal` с пустыми деталями вне DEBUG_MODE."""
    monkeypatch.setattr(settings, "DEBUG_MODE", False)
    response = await http_client.get("/api/v1/core-test/boom")
    assert response.status_code == 500
    assert _error(response) == {"code": "core.internal", "message": "Internal server error", "details": {}}


@pytest.mark.req("SYS-03-R8")
@pytest.mark.req("SYS-05-R15")
async def test_redis_unavailable_is_503(app_with_routes: FastAPI, http_client: AsyncClient) -> None:
    """Недоступный Redis при политике fail-closed — `503 core.service_unavailable` с `Retry-After: 30`."""
    response = await http_client.get("/api/v1/core-test/redis")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert _error(response)["code"] == "core.service_unavailable"


@pytest.mark.req("SYS-03-R22")
@pytest.mark.parametrize("path", ["/api/v1/core-test/forbidden", "/api/v1/core-test/forbidden-new"])
async def test_forbidden_hides_permissions(
    app_with_routes: FastAPI, http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """403 `core.forbidden` не раскрывает недостающие права вне DEBUG_MODE."""
    monkeypatch.setattr(settings, "DEBUG_MODE", False)
    response = await http_client.get(path)
    assert response.status_code == 403
    error = _error(response)
    assert error["code"] == "core.forbidden"
    assert "missing_permissions" not in error["details"]


@pytest.mark.req("SYS-03-R8")
@pytest.mark.req("SYS-03-R22")
async def test_legacy_errors_mapped_to_core_codes(app_with_routes: FastAPI, http_client: AsyncClient) -> None:
    """Ошибки boilerplate: 401 `core.unauthenticated` с `WWW-Authenticate`, 404 `core.not_found` без `is_deleted`."""
    # - Act -
    unauthenticated = await http_client.get("/api/v1/core-test/token")
    missing = await http_client.get("/api/v1/core-test/missing")

    # - Assert -
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["WWW-Authenticate"] == "Bearer"
    assert _error(unauthenticated)["code"] == "core.unauthenticated"
    assert missing.status_code == 404
    assert _error(missing) == {"code": "core.not_found", "message": "Resource not found", "details": {}}


@pytest.mark.req("SYS-03-R19")
async def test_rate_limited_error_envelope(app_with_routes: FastAPI, http_client: AsyncClient) -> None:
    """429 `core.rate_limited`: `Retry-After` округлён вверх, детали `scope` и `retry_after_seconds`."""
    response = await http_client.get("/api/v1/core-test/limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert _error(response) == {
        "code": "core.rate_limited",
        "message": "Rate limit exceeded",
        "details": {"scope": "probe", "retry_after_seconds": 2},
    }
