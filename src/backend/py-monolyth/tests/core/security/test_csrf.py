"""Тесты signed double-submit CSRF-токена (ADR-006, раздел 3.4)."""

from uuid import uuid4

import pytest

from app.core.security.csrf import csrf_token_valid, issue_csrf_token


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-03-R21")]

SECRET = "csrf-test-secret"  # pragma: allowlist secret


def test_issued_token_is_valid_for_its_session() -> None:
    """Токен `<random>.<hmac>` проходит проверку для своей сессии и тем же секретом."""
    # - Arrange -
    sid = uuid4()

    # - Act -
    token = issue_csrf_token(sid, SECRET)

    # - Assert -
    random_part, _, signature = token.partition(".")
    assert random_part and signature
    assert csrf_token_valid(token, sid, SECRET)


def test_tokens_are_random() -> None:
    """Каждый выпуск даёт новый токен (случайная часть 16 байт)."""
    sid = uuid4()
    assert issue_csrf_token(sid, SECRET) != issue_csrf_token(sid, SECRET)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda token, sid: (token, uuid4(), SECRET), id="other-session"),
        pytest.param(lambda token, sid: (token, sid, "other-secret"), id="other-secret"),
        pytest.param(lambda token, sid: (token.split(".")[0] + ".AAAA", sid, SECRET), id="forged-signature"),
        pytest.param(lambda token, sid: ("no-dot", sid, SECRET), id="malformed"),
        pytest.param(lambda token, sid: ("", sid, SECRET), id="empty"),
    ],
)
def test_foreign_or_forged_token_is_rejected(mutate: object) -> None:
    """Токен другой сессии, другого секрета, с подделанной подписью или битый — отклоняется."""
    # - Arrange -
    sid = uuid4()
    token = issue_csrf_token(sid, SECRET)
    candidate, check_sid, secret = mutate(token, sid)  # type: ignore[operator]

    # - Act / Assert -
    assert not csrf_token_valid(candidate, check_sid, secret)
