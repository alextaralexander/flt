"""Unit-тесты хелперов авторизации (`check_permissions`)."""

import pytest

from app.core.exceptions import InsufficientPermissionsError, InvalidTokenError
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import check_permissions


pytestmark = pytest.mark.no_db


def _user(permissions: set[str] | None = None) -> UserSecuritySchema:
    """Пользователь для unit-тестов."""
    return UserSecuritySchema(
        user_id="00000000-0000-0000-0000-000000000002",
        permissions=permissions or set(),
        access_token="test-auth-token",
    )


class TestCheckPermissions:
    """Проверка `check_permissions` (Arrange / Act / Assert)."""

    def test_passes_when_user_has_all_permissions(self) -> None:
        """Не бросает исключение, когда все требуемые права есть."""
        # - Arrange -
        user = _user({"CREATE_MY_ENTITY", "GET_MY_ENTITY"})

        # - Act / Assert -
        check_permissions(user, ["CREATE_MY_ENTITY"])

    def test_passes_on_empty_requirements(self) -> None:
        """Пустой список требований — доступ разрешён любому аутентифицированному."""
        # - Arrange -
        user = _user()

        # - Act / Assert -
        check_permissions(user, [])

    def test_raises_when_permission_is_missing(self) -> None:
        """Не хватает права — `InsufficientPermissionsError`."""
        # - Arrange -
        user = _user({"GET_MY_ENTITY"})

        # - Act / Assert -
        with pytest.raises(InsufficientPermissionsError):
            check_permissions(user, ["DELETE_MY_ENTITY"])


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
