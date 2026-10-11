"""Тесты исключений аутентификации boilerplate, которые остаются в `app.core.exceptions`.

Проверки токенов, CSRF, прав и WebSocket — в `tests/core/security/` (ADR-006, этап 1 Г.4); прежние
тесты заглушки `check_token` (отклонение любого токена до `TokenVerifier`) заменены ими.
"""

import pytest

from app.core.exceptions import InvalidTokenError


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-02-R20")]


class TestInvalidTokenMasking:
    """`InvalidTokenError` не должен раскрывать сырой токен."""

    def test_long_token_is_masked(self) -> None:
        """В сообщении остаётся только 8-символьный префикс токена."""
        # - Arrange -
        token = "secret-token-value-that-must-not-leak"

        # - Act -
        error = InvalidTokenError(token)

        # - Assert -
        assert token not in str(error)
        assert token[:8] in str(error)
