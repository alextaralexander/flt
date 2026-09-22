"""Unit-тесты `AuthService` и `check_token`: локальная верификация JWT и сборка permissions."""

import time

import jwt
import pytest

from app.core.exceptions import InvalidTokenError
from app.core.security.auth_service import AuthService, get_auth_service, reset_auth_service
from app.core.security.security import check_token as real_check_token
from tests.settings import test_settings


pytestmark = pytest.mark.no_db

# 32+ байта: HS256 требует ключ не короче рекомендованного (RFC 7518, 3.2).
SIGN_KEY = "unit-test-sign-key-0123456789-abcdef"
WRONG_SIGN_KEY = "wrong-sign-key-0123456789-abcdefghij"

# `real_check_token` — ссылка на настоящую функцию, взятая при импорте:
# для no_db-тестов conftest подменяет атрибут `security.check_token`.


def make_service(issuer: str = "", role_permissions: dict[str, list[str]] | None = None) -> AuthService:
    """AuthService с тестовым ключом."""
    return AuthService(SIGN_KEY, issuer=issuer, role_permissions=role_permissions)


class TestVerifyToken:
    """Проверка `verify_token` (Arrange / Act / Assert)."""

    def test_returns_payload_for_valid_token(self) -> None:
        """Выпущенный сервисом токен декодируется в исходный payload."""
        # - Arrange -
        service = make_service()
        token = service.create_token("user-1")

        # - Act -
        decoded = service.verify_token(token)

        # - Assert -
        assert decoded["USER_ID"] == "user-1"

    def test_raises_for_wrong_signature(self) -> None:
        """Токен с чужой подписью — `InvalidTokenError`."""
        # - Arrange -
        service = make_service()
        token = jwt.encode({"USER_ID": "user-1", "exp": int(time.time()) + 60}, WRONG_SIGN_KEY, algorithm="HS256")

        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            service.verify_token(token)

    def test_raises_for_expired_token(self) -> None:
        """Истёкший токен — `InvalidTokenError`."""
        # - Arrange -
        service = make_service()
        token = service.create_token("user-1", expires_in_seconds=-10)

        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            service.verify_token(token)

    def test_raises_without_exp(self) -> None:
        """Токен без `exp` не принимается."""
        # - Arrange -
        service = make_service()
        token = jwt.encode({"USER_ID": "user-1"}, SIGN_KEY, algorithm="HS256")

        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            service.verify_token(token)

    def test_raises_for_foreign_issuer(self) -> None:
        """При заданном `JWT_ISSUER` токен другого издателя отклоняется."""
        # - Arrange -
        service = make_service(issuer="https://idp.example.com")
        token = make_service(issuer="https://evil.example.com").create_token("user-1")

        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            service.verify_token(token)

    def test_rejects_other_algorithm(self) -> None:
        """Разрешён только настроенный алгоритм (защита от подмены `alg`)."""
        # - Arrange -
        service = make_service()
        token = jwt.encode({"USER_ID": "user-1", "exp": int(time.time()) + 60}, SIGN_KEY * 2, algorithm="HS512")

        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            service.verify_token(token)

    def test_empty_sign_key_is_rejected(self) -> None:
        """Сервис без ключа подписи не создаётся."""
        # - Act / Assert -
        with pytest.raises(ValueError):
            AuthService("")


class TestPermissionsAssembly:
    """Сборка permissions из claims `PERMISSIONS` и `ROLES`."""

    def test_merges_direct_and_role_permissions(self) -> None:
        """Объединяются прямые permissions и права ролей; неизвестная роль игнорируется."""
        # - Arrange -
        service = make_service(role_permissions={"ADMIN": ["ROLE_PERMISSION"]})
        payload = {"PERMISSIONS": ["DIRECT_PERMISSION"], "ROLES": ["ADMIN", "UNKNOWN"]}

        # - Act -
        permissions = service.get_permissions(payload)

        # - Assert -
        assert permissions == {"DIRECT_PERMISSION", "ROLE_PERMISSION"}

    def test_user_id_falls_back_to_sub(self) -> None:
        """Без `USER_ID` идентификатором служит `sub`."""
        # - Act / Assert -
        assert AuthService.get_user_id({"sub": "user-2"}) == "user-2"
        assert AuthService.get_user_id({}) is None


class TestCheckToken:
    """Настоящий `check_token` поверх настроек стенда pytest (без моков)."""

    async def test_test_token_is_valid(self) -> None:
        """Токен из `envs/.test.env` проходит реальную проверку."""
        # - Arrange -
        reset_auth_service()

        # - Act -
        user = await real_check_token(test_settings.TEST_AUTH_TOKEN)

        # - Assert -
        assert user.user_id == test_settings.TEST_USER_ID
        assert "GET_MY_ENTITY" in user.permissions

    async def test_token_without_user_raises(self) -> None:
        """Токен без `USER_ID`/`sub` — `InvalidTokenError`."""
        # - Arrange -
        service = get_auth_service()
        token = jwt.encode({"exp": int(time.time()) + 60}, service.sign_key, algorithm=service.algorithm)

        # - Act / Assert -
        with pytest.raises(InvalidTokenError):
            await real_check_token(token)
