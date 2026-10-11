"""Таблица кодов ошибок shared kernel и английские сообщения (SYS-03-R8, SYS-07-R12)."""

import re
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.orm.exc import StaleDataError

from app.core.http.errors import CORE_ERRORS, DomainError, RateLimitedError, VersionConflictError


pytestmark = pytest.mark.no_db

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

# Таблица SYS-03-R8 (коды shared kernel).
EXPECTED_STATUS = {
    "core.bad_request": 400,
    "core.invalid_cursor": 400,
    "core.unauthenticated": 401,
    "core.forbidden": 403,
    "core.not_found": 404,
    "core.method_not_allowed": 405,
    "core.version_conflict": 409,
    "core.request_in_progress": 409,
    "core.payload_too_large": 413,
    "core.unsupported_media_type": 415,
    "core.validation_failed": 422,
    "core.idempotency_key_reused": 422,
    "core.rate_limited": 429,
    "core.internal": 500,
    "core.service_unavailable": 503,
}


@pytest.mark.req("SYS-03-R8")
def test_core_error_codes_match_table() -> None:
    """Коды `core.*` и их HTTP-статусы совпадают с таблицей SYS-03-R8, коды уникальны."""
    # - Act -
    table = {error.code: error.http_status for error in CORE_ERRORS}

    # - Assert -
    assert table == EXPECTED_STATUS
    assert len({error.code for error in CORE_ERRORS}) == len(CORE_ERRORS)
    for code in table:
        assert CODE_PATTERN.fullmatch(code), code
        assert code.startswith("core.")


@pytest.mark.req("SYS-07-R12")
def test_error_messages_are_english() -> None:
    """Сообщения ошибок shared kernel — ASCII-текст для разработчика, не перевод."""
    for error in (DomainError, *CORE_ERRORS):
        assert error.message.isascii(), error.__name__
        assert error.message


@pytest.mark.req("SYS-03-R17")
def test_version_conflict_details() -> None:
    """`VersionConflictError` несёт `details.current_version`, если версия известна."""
    assert VersionConflictError(current_version=5).details == {"current_version": 5}
    assert VersionConflictError().details == {}


@pytest.mark.req("SYS-03-R19")
def test_rate_limited_rounds_retry_after_up() -> None:
    """`Retry-After` — целые секунды, округлённые вверх, не меньше 1."""
    assert RateLimitedError("s", timedelta(milliseconds=1)).headers == {"Retry-After": "1"}
    assert RateLimitedError("s", timedelta(seconds=2, milliseconds=1)).details["retry_after_seconds"] == 3


@pytest.mark.req("SYS-05-R18")
@pytest.mark.req("SYS-03-R17")
async def test_stale_data_to_409(http_app: FastAPI, http_client: AsyncClient) -> None:
    """`StaleDataError` ORM (конкурентное изменение версии) — `409 core.version_conflict`."""

    # - Arrange -
    @http_app.patch("/api/v1/core-test/stale")
    async def stale() -> None:
        raise StaleDataError("UPDATE statement on table expected to update 1 row(s); 0 were matched.")

    @http_app.patch("/api/v1/core-test/conflict")
    async def conflict() -> None:
        raise VersionConflictError(current_version=7)

    # - Act -
    stale_response = await http_client.patch("/api/v1/core-test/stale")
    conflict_response = await http_client.patch("/api/v1/core-test/conflict")

    # - Assert -
    assert stale_response.status_code == 409
    assert stale_response.json()["messages"]["ERROR"][0]["code"] == "core.version_conflict"
    assert conflict_response.status_code == 409
    assert conflict_response.json()["messages"]["ERROR"][0]["details"] == {"current_version": 7}
