"""Тесты хелперов авторизации (`check_permissions`, `check_token`)."""

from typing import Annotated

import pytest
from fastapi import Security
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import InsufficientPermissionsError, InvalidTokenError
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user, check_permissions, check_token
from app.main import create_app


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-02-R20")]


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
        user = _user({"sample:items:create", "sample:items:read"})

        # - Act / Assert -
        check_permissions(user, ["sample:items:create"])

    def test_passes_on_empty_requirements(self) -> None:
        """Пустой список требований — доступ разрешён любому аутентифицированному."""
        # - Arrange -
        user = _user()

        # - Act / Assert -
        check_permissions(user, [])

    def test_raises_when_permission_is_missing(self) -> None:
        """Не хватает права — `InsufficientPermissionsError`."""
        # - Arrange -
        user = _user({"sample:items:read"})

        # - Act / Assert -
        with pytest.raises(InsufficientPermissionsError):
            check_permissions(user, ["sample:items:delete"])


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


class TestCheckTokenFailClosed:
    """До `TokenVerifier` (этап 1 Г.4) любой токен отклоняется, а не пропускается без проверки."""

    async def test_any_token_is_rejected(self) -> None:
        """`check_token` бросает `InvalidTokenError` для любого токена."""
        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            await check_token("any-token")

    async def test_protected_endpoint_answers_401(self) -> None:
        """Эндпоинт с `auth_user` без подмены аутентификации отвечает 401 в конверте ошибок."""
        # - Arrange -
        application = create_app([])

        @application.get("/protected")
        async def protected(user: Annotated[UserSecuritySchema, Security(auth_user())]) -> dict[str, str]:
            """Защищённый тестовый ресурс."""
            return {"user_id": user.user_id}

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            response = await client.get("/protected", headers={"Authorization": "Bearer some-token"})

        # - Assert -
        assert response.status_code == 401
        assert response.json()["messages"]["ERROR"][0]["message_mnemo_code"] == "INVALID_TOKEN"
