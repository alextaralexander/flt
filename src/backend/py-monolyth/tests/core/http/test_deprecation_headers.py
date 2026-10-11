"""Заголовки вывода операции из эксплуатации: `Deprecation`, `Sunset`, `Link` (SYS-03-R28)."""

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.http.deprecation import deprecated


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-03-R28")]

SINCE = date(2026, 10, 11)
SUNSET = date(2027, 3, 1)


@pytest.fixture
def deprecated_app(http_app: FastAPI) -> FastAPI:
    """Приложение с устаревшим и обычным роутами."""

    @http_app.get("/api/v1/core-test/old")
    @deprecated(since=SINCE, sunset=SUNSET, successor="/api/v1/core-test/new")
    async def old() -> dict[str, str]:
        return {"version": "old"}

    @http_app.get("/api/v1/core-test/new")
    async def new() -> dict[str, str]:
        return {"version": "new"}

    return http_app


async def test_deprecated_route_sets_headers(deprecated_app: FastAPI, http_client: AsyncClient) -> None:
    """Устаревшая операция отдаёт `Deprecation: @<unix>`, `Sunset` (HTTP-date) и `Link` на замену."""
    response = await http_client.get("/api/v1/core-test/old")
    assert response.status_code == 200
    since_ts = int(datetime(2026, 10, 11, tzinfo=UTC).timestamp())
    assert response.headers["Deprecation"] == f"@{since_ts}"
    assert response.headers["Sunset"] == "Mon, 01 Mar 2027 00:00:00 GMT"
    assert response.headers["Link"] == '</api/v1/core-test/new>; rel="successor-version"'


async def test_regular_route_has_no_headers(deprecated_app: FastAPI, http_client: AsyncClient) -> None:
    """Обычная операция заголовков вывода не отдаёт."""
    response = await http_client.get("/api/v1/core-test/new")
    assert "Deprecation" not in response.headers
    assert "Sunset" not in response.headers


def test_sunset_must_be_at_least_90_days_after_since() -> None:
    """Срок между `Deprecation` и `Sunset` — не менее 90 дней; иначе ошибка при объявлении роута."""
    with pytest.raises(ValueError, match="90"):
        deprecated(since=SINCE, sunset=date(2026, 11, 1))
