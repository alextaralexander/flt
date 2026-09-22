from typing import Any, Dict, List, Type, Union

from py_main_lib.entities.alchemy import BaseEntityModel
from py_main_lib.security.schemas import UserSecuritySchema


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
        self.message_mnemo_code = message_mnemo_code or self.__class__.__name__
        self.description = description or "Error description for developers."
        self.message = message or f"Error `{self.message_mnemo_code}`."
        self.parameters = parameters

        super().__init__(self.message)


class ModelNotFoundInCacheError(BaseCustomException):
    """todo"""


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
        model: Type[BaseEntityModel],
        is_deleted: bool | None = False,
    ) -> None:

        super().__init__(
            message=f"{model.__name__} with ID `{model_id}` not found in Database, is_deleted is {is_deleted}.",
            description="Occurs when the entity is not found in the database or is marked as `is_deleted`.",
            message_mnemo_code="MODEL_NOT_FOUND_IN_DATABASE_ERROR",
            model_id=model_id,
            model_name=model.__name__,
            is_deleted=is_deleted,
        )


class GraphIsNotConsistencyError(BaseCustomException):
    """Исключение, возникающее если граф не консистентен."""

    def __init__(
        self,
        message: str,
    ) -> None:

        super().__init__(
            message=f"{message}",
            description="Todo.",
            message_mnemo_code="GRAPH_IS_NOT_CONSISTENCY_ERROR",
        )


class MsAuthIsNotAvailableError(BaseCustomException):
    """Исключение, возникающее если сервис авторизации недоступен, либо возвращена 500 ошибка.

    Args:
        url: Адрес, на который был отправлен запрос
    """

    def __init__(
        self,
        url: str,
        method: str,
    ) -> None:
        self.description = "Occurs when the authentication service is unavailable or returns a 500 status_code."
        super().__init__(
            message_mnemo_code="MS_AUTH_IS_NOT_AVAILABLE_ERROR",
            message=f"ms-auth service is malfunctioning or unavailable.\n" f"Method: {method}\n" f"URL: {url}",
        )


class InsufficientPermissionsError(BaseCustomException):
    """Исключение, возникающее при недостатке прав у пользователя для вызова контроллера.

    Args:
        user: Пользователь, отправивший запрос.
    """

    def __init__(
        self,
        user: Union[UserSecuritySchema | UserSecuritySchema],
        permissions_to_check: List[str],
    ) -> None:
        missing_permissions = tuple(set(permissions_to_check) - set(user.permissions))

        self.description = "Occurs when the user does not have sufficient permissions to call the controller."
        super().__init__(
            message_mnemo_code="INSUFFICIENT_PERMISSIONS_ERROR",
            message=f"User `{user.user_id}` doesn't have permissions: {missing_permissions}.",
            missing_permissions=missing_permissions,
        )


class InvalidTokenError(BaseCustomException):
    """Исключение, возникающее если токен авторизации невалидный.

    Args:
        token: Токен авторизации.
    """

    def __init__(
        self,
        token: str,
    ) -> None:

        self.description = "Todo."
        super().__init__(
            message_mnemo_code="INVALID_TOKEN",
            message=f"Token `{token}` invalid .",
        )


class ValidationError(BaseCustomException):
    def __init__(
        self,
        message: str,
        parameters: Dict[str, Union[str, int, List[str]]],
        message_mnemo_code: str | None = None,
    ):

        message_mnemo_code = message_mnemo_code or "VALIDATION_ERROR"
        super().__init__(
            message_mnemo_code=message_mnemo_code,
            description="",
            parameters=parameters,
            message=message,
        )


class FolderIsNotEmpty(BaseCustomException):
    def __init__(
        self,
        parameters: Dict[str, Union[str, int, List[str]]],
    ):

        super().__init__(
            message_mnemo_code="FOLDER_IS_NOT_EMPTY_ERROR",
            description="",
            parameters=parameters,
            message="Folder is not empty.",
        )
