"""Тесты exception handler-ов HTTP-слоя: ошибки boilerplate в конверте `ErrorResponseV1` (SYS-03-R7, R8)."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.exceptions import (
    InsufficientPermissionsError,
    InvalidTokenError,
    ModelNotFoundInDatabaseError,
)
from app.core.http.schemas import ErrorResponseV1
from app.core.security.schemas import UserSecuritySchema
from configs.settings import settings
from tests.conftest import mocked_function


pytestmark = pytest.mark.req("SYS-03-R7")


class SampleModel:
    """Класс-заглушка модели: обработчику 404 нужно только имя класса."""


class TestExceptionHandlers:
    """Класс с тестами для проверки работы Exception Handlers для FastAPI приложения.

    Структура тестов представляет собой Act-Arrange-Assert. Данный шаблон организации тестов имеет:
    - `# - Arrange`, здесь создаются все необходимые данные, объекты или условия, необходимые для теста.
    - `# - Act -`, здесь выполняется тестируемая операция, их может быть несколько.
    - `# - Assert -`, здесь проверяется, соответствует ли результат ожидаемым значениям.
    - (Дополнительно) `# - Clean -`, здесь удаляем объекты из БД, чтобы не влияли на другие тесты.
    """

    async def test_model_not_found_in_database_error_exception_handler(
        self,
        overridden_app: FastAPI,
        client: AsyncClient,
    ) -> None:
        """Тест exception_handler `ModelNotFoundInDatabaseError`.

        Проверки:
        - Корректный статус код.
        - Код `core.not_found`.
        - Детали не раскрывают, существует ли объект (SYS-03-R22).
        """
        # - Arrange -
        param_model_id = str(uuid4())
        param_model = SampleModel

        def raise_model_not_found_in_database_error() -> None:
            """Перезаписывающая функция, что вызовет ошибку."""
            raise ModelNotFoundInDatabaseError(model_id=param_model_id, model=param_model)

        overridden_app.dependency_overrides[mocked_function] = raise_model_not_found_in_database_error

        # - Act -
        response = await client.get("/mocked_endpoint")

        # - Assert -
        response_schema = ErrorResponseV1(**response.json())
        assert response.status_code == 404
        assert response_schema.messages.ERROR[0].code == "core.not_found"
        assert response_schema.messages.ERROR[0].details == {}
        assert param_model_id not in response.text

    async def test_model_not_found_hides_is_deleted_without_debug_mode(
        self,
        overridden_app: FastAPI,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Вне DEBUG_MODE клиент не должен узнать, существует ли объект (`is_deleted`).

        Проверки:
        - Параметр `is_deleted` скрыт из ответа.
        """
        # - Arrange -
        monkeypatch.setattr(settings, "DEBUG_MODE", False)

        def raise_error() -> None:
            """Перезаписывающая функция, что вызовет ошибку."""
            raise ModelNotFoundInDatabaseError(model_id=str(uuid4()), model=SampleModel, is_deleted=True)

        overridden_app.dependency_overrides[mocked_function] = raise_error

        # - Act -
        response = await client.get("/mocked_endpoint")

        # - Assert -
        details = response.json()["messages"]["ERROR"][0]["details"]
        assert response.status_code == 404
        assert "is_deleted" not in details

    async def test_insufficient_permission_error_handler(
        self,
        overridden_app: FastAPI,
        client: AsyncClient,
        test_user: UserSecuritySchema,
    ) -> None:
        """Тест exception_handler `InsufficientPermissionsError`.

        Проверки:
        - Корректный статус код.
        - Код `core.forbidden`.
        """

        # - Arrange -
        def raise_exception() -> None:
            """Перезаписывающая функция, что вызовет ошибку."""
            raise InsufficientPermissionsError(test_user, ["InsufficientPermission"])

        overridden_app.dependency_overrides[mocked_function] = raise_exception

        # - Act -
        response = await client.get("/mocked_endpoint")

        # - Assert -
        response_schema = ErrorResponseV1(**response.json())
        assert response.status_code == 403
        assert response_schema.messages.ERROR[0].code == "core.forbidden"

    async def test_invalid_token_error_handler(
        self,
        overridden_app: FastAPI,
        client: AsyncClient,
    ) -> None:
        """Тест exception_handler `InvalidTokenError`.

        Проверки:
        - Корректный статус код (401).
        - Код `core.unauthenticated` и заголовок `WWW-Authenticate: Bearer`.
        """

        # - Arrange -
        def raise_exception() -> None:
            """Перезаписывающая функция, что вызовет ошибку."""
            raise InvalidTokenError("invalid_token")

        overridden_app.dependency_overrides[mocked_function] = raise_exception

        # - Act -
        response = await client.get("/mocked_endpoint")

        # - Assert -
        assert response.status_code == 401
        assert response.json()["messages"]["ERROR"][0]["code"] == "core.unauthenticated"
        assert response.headers["WWW-Authenticate"] == "Bearer"

    async def test_request_validation_error_uses_error_envelope(
        self,
        client: AsyncClient,
    ) -> None:
        """Ошибки валидации запроса (422) — в едином конверте `ErrorResponseV1`.

        Проверки:
        - Корректный статус код (422).
        - Код `core.validation_failed`.
        - Детали валидации присутствуют в details.errors.
        """
        # - Act -
        response = await client.post("/mocked_body", json={})

        # - Assert -
        error = response.json()["messages"]["ERROR"][0]
        assert response.status_code == 422
        assert error["code"] == "core.validation_failed"
        assert error["details"]["errors"]

    async def test_http_exception_uses_error_envelope(
        self,
        client: AsyncClient,
    ) -> None:
        """`HTTPException` (404 несуществующего маршрута) — в том же конверте, что и доменные ошибки.

        Проверки:
        - Корректный статус код (404).
        - Код `core.not_found`.
        """
        # - Act -
        response = await client.get("/route/that/does/not/exist")

        # - Assert -
        error = response.json()["messages"]["ERROR"][0]
        assert response.status_code == 404
        assert error["code"] == "core.not_found"
