"""Тесты локали запроса в HTTP-слое (SYS-03-R30, SYS-07-R3, R6)."""

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import AsyncClient

from app.core.http.context import RequestContextDep, set_request_user


pytestmark = pytest.mark.no_db


async def _profile_user(request: Request) -> None:
    """Тестовая аутентификация: пользователь с языком профиля из заголовка `X-Test-Profile-Language`."""
    language = request.headers.get("X-Test-Profile-Language")
    if language is not None:
        set_request_user(request, SimpleNamespace(user_id="u1", ui_language=language))


@pytest.fixture
def locale_app(http_app: FastAPI) -> FastAPI:
    """Приложение с роутом, возвращающим локаль запроса."""

    @http_app.get("/api/v1/core-test/locale", dependencies=[Depends(_profile_user)])
    async def locale(ctx: RequestContextDep) -> dict[str, str]:
        return {"locale": ctx.locale}

    return http_app


@pytest.mark.req("SYS-03-R30")
@pytest.mark.req("SYS-07-R3")
@pytest.mark.parametrize(
    ("profile", "cookie", "accept", "expected"),
    [
        ("ar", "en", "en", "ar"),
        (None, "en", "ar", "en"),
        (None, None, "de, ar;q=0.8", "ar"),
        (None, None, None, "ru"),
        ("de", "fr", "en-GB,en;q=0.9", "en"),
        (None, "", "zh-Hans", "ru"),
    ],
)
async def test_locale_priority(
    locale_app: FastAPI,
    http_client: AsyncClient,
    profile: str | None,
    cookie: str | None,
    accept: str | None,
    expected: str,
) -> None:
    """Профиль → cookie `flt_ui_language` → `Accept-Language` → `ru`; недопустимые значения пропускаются."""
    # - Arrange -
    headers: dict[str, str] = {}
    if profile is not None:
        headers["X-Test-Profile-Language"] = profile
    if cookie is not None:
        headers["Cookie"] = f"flt_ui_language={cookie}"
    if accept is not None:
        headers["Accept-Language"] = accept

    # - Act -
    response = await http_client.get("/api/v1/core-test/locale", headers=headers)

    # - Assert -
    assert response.json() == {"locale": expected}
    assert response.headers["Content-Language"] == expected


@pytest.mark.req("SYS-03-R30")
async def test_content_language_on_error_without_dependency(locale_app: FastAPI, http_client: AsyncClient) -> None:
    """`Content-Language` есть и у ответов, где зависимость локали не вызывалась (cookie → `Accept-Language`)."""
    response = await http_client.get(
        "/api/v1/core-test/none", headers={"Cookie": "flt_ui_language=ar", "Accept-Language": "en"}
    )
    assert response.status_code == 404
    assert response.headers["Content-Language"] == "ar"


@pytest.mark.req("SYS-07-R6")
async def test_backend_does_not_set_language_cookie(locale_app: FastAPI, http_client: AsyncClient) -> None:
    """Backend только читает cookie `flt_ui_language` и не устанавливает её."""
    response = await http_client.get("/api/v1/core-test/locale", headers={"Accept-Language": "ar"})
    assert "flt_ui_language" not in response.headers.get("set-cookie", "")
