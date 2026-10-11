"""Тесты определения языка запроса (SYS-07-R3, R6; SYS-03-R30)."""

import pytest

from app.core.i18n import pick_from_accept_language, request_language


pytestmark = pytest.mark.no_db


@pytest.mark.req("SYS-07-R3")
@pytest.mark.parametrize(
    ("profile", "cookie", "accept", "expected"),
    [
        ("ar", None, "en", "ar"),
        (None, "en", "ar", "en"),
        (None, None, "de, ar;q=0.8", "ar"),
        (None, None, None, "ru"),
        ("de", None, "en", "en"),
    ],
)
def test_priority_table(profile: str | None, cookie: str | None, accept: str | None, expected: str) -> None:
    """Таблица случаев SYS-07-R3: профиль → cookie → `Accept-Language` → `ru`."""
    assert request_language(profile_language=profile, cookie_language=cookie, accept_language=accept) == expected


@pytest.mark.req("SYS-07-R6")
@pytest.mark.parametrize("cookie", ["fr", "", "AR", "ar-EG"])
def test_unsupported_cookie_ignored(cookie: str) -> None:
    """Значение cookie вне `ru`, `en`, `ar` игнорируется (переход к `Accept-Language`)."""
    assert request_language(profile_language=None, cookie_language=cookie, accept_language="en") == "en"


@pytest.mark.req("SYS-07-R3")
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("ar-EG,ar;q=0.9,en;q=0.8", "ar"),
        ("en-GB,en;q=0.9", "en"),
        ("de;q=1.0, en;q=0.2, ru;q=0.5", "ru"),
        ("fr, en;q=0", "ru"),
        ("*, en;q=0.1", "en"),
        ("zh-Hans", "ru"),
        ("en;q=abc, ar", "ar"),
        ("  ,  ", "ru"),
        ("RU-ru", "ru"),
        ("ar;q=0.5, en;q=0.5", "ar"),
    ],
)
def test_accept_language_parsing(header: str, expected: str) -> None:
    """Разбор `Accept-Language` по q-весам с отбрасыванием региона (RFC 9110)."""
    assert pick_from_accept_language(header) == expected
