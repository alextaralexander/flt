"""Доменные исключения сервиса (единый формат: мнемокод + параметры)."""

from typing import Any

from app.core.dao.models import SchemaBase
from app.core.security.schemas import UserSecuritySchema


class BaseCustomException(Exception):
    """Базовый класс для всех пользовательских исключений.

    Attributes:
          message_mnemo_code (str): Уникальный код ошибки, по умолчанию совпадает с именем класса;
          description (str): Описание ошибки для разработчиков;
          message (str): Сообщение об ошибке в логе при возникновении исключения;
          parameters (dict): Дополнительные параметры ошибки, передаваемые в виде именованных аргументов.
    """

    def __init__(
        self,
        message_mnemo_code: str | None = None,
        description: str | None = None,
        message: str | None = None,
        **parameters: Any,
    ) -> None:
        """Собирает мнемокод, описание, сообщение и параметры ошибки."""
        self.message_mnemo_code = message_mnemo_code or self.__class__.__name__
        self.description = description or "Error description for developers."
        self.message = message or f"Error `{self.message_mnemo_code}`."
        self.parameters = parameters

        super().__init__(self.message)


class ModelNotFoundInDatabaseError(BaseCustomException):
    """Исключение, возникающее при отсутствии указанной сущности в базе данных или при
    положительном значении поля is_deleted.

    Args:
        model_id: ID сущности, что не была найдена;
        model: Название модели, по которой был произведен поиск;
        is_deleted: Объект был найден, но маркирован как удаленный.
    """

    def __init__(
        self,
        model_id: str,
        model: type[SchemaBase],
        is_deleted: bool = False,
    ) -> None:
        """Формирует 404-ошибку по модели и ID (is_deleted попадает в параметры)."""
        super().__init__(
            message=f"{model.__name__} with ID `{model_id}` not found in Database, is_deleted is {is_deleted}.",
            description="Occurs when the entity is not found in the database or is marked as `is_deleted`.",
            message_mnemo_code="MODEL_NOT_FOUND_IN_DATABASE_ERROR",
            model_id=model_id,
            model_name=model.__name__,
            is_deleted=is_deleted,
        )


class InsufficientPermissionsError(BaseCustomException):
    """Исключение, возникающее при недостатке прав у пользователя для вызова контроллера.

    Args:
        user: Пользователь, отправивший запрос.
    """

    def __init__(
        self,
        user: UserSecuritySchema,
        permissions_to_check: list[str],
    ) -> None:
        """Вычисляет недостающие permissions и формирует 403-ошибку."""
        missing_permissions = tuple(set(permissions_to_check) - set(user.permissions))

        self.description = "Occurs when the user does not have sufficient permissions to call the controller."
        super().__init__(
            message_mnemo_code="INSUFFICIENT_PERMISSIONS_ERROR",
            message=f"User `{user.user_id}` doesn't have permissions: {missing_permissions}.",
            missing_permissions=missing_permissions,
        )


class InvalidTokenError(BaseCustomException):
    """Исключение, возникающее если токен авторизации невалидный.

    В сообщение попадает только маскированный префикс токена: сырой токен
    не должен утекать в логи и ответы.

    Args:
        token: Токен авторизации.
    """

    def __init__(
        self,
        token: str,
    ) -> None:
        """Формирует 401-ошибку с маскированным префиксом токена."""
        masked_token = f"{token[:8]}..." if len(token) > 8 else "***"

        self.description = "Occurs when the authorization token fails verification."
        super().__init__(
            message_mnemo_code="INVALID_TOKEN",
            message=f"Token `{masked_token}` is invalid.",
        )
