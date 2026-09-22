"""Шаблоны генерируемого кода.

Шаблоны используют токены `__PASCAL__`, `__SNAKE__`, `__UPPER__`, `__CONST__`, `__VALUE__`
и подставляются простым `str.replace`, чтобы не экранировать фигурные скобки Python-кода.
"""


def render(template: str, **tokens: str) -> str:
    """Подставить токены вида `__NAME__` в шаблон.

    Args:
        template: Текст шаблона с токенами.
        **tokens: Пары `NAME=value` (ключ — без подчёркиваний-обрамления).

    Returns:
        Готовый текст.
    """
    result = template
    for key, value in tokens.items():
        result = result.replace(f"__{key}__", value)
    return result


# --- REST-сущность ---------------------------------------------------------

ENTITY_SCHEMA = '''"""Schema для `__PASCAL__`."""

from uuid import UUID

from py_main_lib.filter_utils.schemas.filter_schema import FilterResult
from py_main_lib.services.schemas.v1_schemas import SuccessfulResponseV1
from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Base__PASCAL__Schema(BaseModel):
    """Базовая схема `__PASCAL__`."""

    name: str = Field(
        description="Название",
        examples=["Example"],
    )


class __PASCAL__Schema(Base__PASCAL__Schema):
    """Схема `__PASCAL__`."""

    id: UUID = Field(
        description="ID",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, value: UUID) -> str:
        """Сериализация UUID в строковый формат."""
        return str(value)


class Create__PASCAL__Schema(Base__PASCAL__Schema):
    """Создание `__PASCAL__`."""

    model_config = ConfigDict(from_attributes=True)


class Update__PASCAL__Schema(Base__PASCAL__Schema):
    """Обновление `__PASCAL__`."""

    model_config = ConfigDict(from_attributes=True)


class __PASCAL__Response(SuccessfulResponseV1):
    """Ответ с одной сущностью `__PASCAL__` в стандартном конверте."""

    payload: __PASCAL__Schema = Field(
        description="Найденная/изменённая сущность.",
    )


class __PASCAL__FilterResult(FilterResult):
    """Страница результатов фильтрации `__PASCAL__` (+пагинация из FilterResult)."""

    result: list[__PASCAL__Schema] = Field(
        description="Сущности текущей страницы.",
    )


class Filtered__PASCAL__Response(SuccessfulResponseV1):
    """Ответ фильтрации `__PASCAL__` в стандартном конверте."""

    payload: __PASCAL__FilterResult = Field(
        description="Результат фильтрации с пагинацией.",
    )
'''


ENTITY_DAO = '''"""Репозиторий для работы с `__PASCAL__`."""

from py_main_lib.dao.base_dao import BaseDAO

from app.api.schemas.__SNAKE___schema import Create__PASCAL__Schema, Update__PASCAL__Schema
from app.core.dao.models import __PASCAL__


class __PASCAL__DAO(BaseDAO[__PASCAL__, Create__PASCAL__Schema, Update__PASCAL__Schema]):
    """Репозиторий для работы с моделью `__PASCAL__`."""

    model = __PASCAL__
'''


ENTITY_SERVICE = '''"""Сервис бизнес-логики для `__PASCAL__`."""

from typing import Any, ClassVar
from uuid import UUID

from py_main_lib.db_utils import transaction_context
from py_main_lib.filter_utils.base_compare_methods import equals, like_
from py_main_lib.security.schemas import UserSecuritySchema
from py_main_lib.services.base_crud_service import BaseService
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dao.__SNAKE___dao import __PASCAL__DAO
from app.api.schemas.__SNAKE___schema import (
    Create__PASCAL__Schema,
    __PASCAL__Schema,
    Update__PASCAL__Schema,
)
from app.core.dao.models import __PASCAL__
from app.core.exceptions import ModelNotFoundInDatabaseError


class __PASCAL__Service(BaseService[__PASCAL__Schema, Create__PASCAL__Schema, Update__PASCAL__Schema]):
    """Бизнес-логика для сущности `__PASCAL__`."""

    dao = __PASCAL__DAO
    schema = __PASCAL__Schema
    filter_conditions: ClassVar[dict[str, Any]] = {"name": like_, "created_by": equals}
    sort_conditions = ("name",)

    async def get_object_by_id(self, obj_id: UUID, user: UserSecuritySchema, session: AsyncSession) -> __PASCAL__:
        """Получение объекта по ID.

        Args:
            obj_id: ID объекта.
            user: Пользователь, выполняющий запрос.
            session: Асинхронная сессия базы данных.

        Returns:
            Найденный объект.

        Raises:
            ModelNotFoundInDatabaseError: объект не найден или помечен удалённым.
        """
        async with transaction_context(session):
            obj = await self.dao.get_by_id(obj_id, session)
            if not obj:
                raise ModelNotFoundInDatabaseError(model_id=str(obj_id), model=__PASCAL__)
            if obj.is_deleted:
                raise ModelNotFoundInDatabaseError(model_id=str(obj_id), model=__PASCAL__, is_deleted=obj.is_deleted)
        return obj
'''


ENTITY_CONTROLLER = '''"""Контроллер для `__PASCAL__`."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, Security, status
from py_main_lib.filter_utils.schemas.filter_schema import FilterSchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.__SNAKE___schema import (
    Create__PASCAL__Schema,
    Filtered__PASCAL__Response,
    __PASCAL__Response,
    Update__PASCAL__Schema,
)
from app.api.services.__SNAKE___service import __PASCAL__Service
from app.core.dao.db_helpers.db_connection import get_session
from app.core.security.permissions import __PASCAL__Permissions
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user


router = APIRouter(prefix="/__SNAKE__", tags=["__SNAKE___api"])

ServiceDep = Annotated[__PASCAL__Service, Depends()]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Создание нового объекта",
    description="Создание нового объекта",
    operation_id="create___SNAKE__",
)
async def create_object(
    create_dto: Create__PASCAL__Schema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[__PASCAL__Permissions.CREATE_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> __PASCAL__Response:
    """Создание нового объекта.

    Args:
        create_dto: Данные для создания объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `__PASCAL__`.
        session: Асинхронная сессия базы данных.

    Returns:
        Созданный объект.
    """
    result = await service.create_object(create_dto, user, session)
    return __PASCAL__Response(payload=result)


@router.post(
    "/filter",
    status_code=status.HTTP_200_OK,
    summary="Фильтрация объектов по заданным критериям",
    description="Фильтрация объектов по заданным критериям",
    operation_id="filter___SNAKE__",
)
async def get_filtered_list(
    filter_dto: FilterSchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[__PASCAL__Permissions.GET_LIST])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> Filtered__PASCAL__Response:
    """Получение списка объектов с фильтрацией.

    Args:
        filter_dto: Параметры фильтрации.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `__PASCAL__`.
        session: Асинхронная сессия базы данных.

    Returns:
        Отфильтрованный список объектов.
    """
    payload = await service.get_objects_filtered(filter_dto, user, session)
    return Filtered__PASCAL__Response(payload=payload.model_dump())


@router.get(
    "/{obj_id}",
    status_code=status.HTTP_200_OK,
    summary="Получение объекта по ID",
    description="Получение объекта по ID",
    operation_id="get___SNAKE__",
)
async def get_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[__PASCAL__Permissions.GET_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> __PASCAL__Response:
    """Получение объекта по ID.

    Args:
        obj_id: ID объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `__PASCAL__`.
        session: Асинхронная сессия базы данных.

    Returns:
        Найденный объект.
    """
    result = await service.get_object_by_id(obj_id, user, session)
    return __PASCAL__Response(payload=result)


@router.put(
    "/{obj_id}",
    status_code=status.HTTP_200_OK,
    summary="Обновление объекта по ID",
    description="Обновление объекта по ID",
    operation_id="update___SNAKE__",
)
async def update_object(
    obj_id: UUID,
    update_dto: Update__PASCAL__Schema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[__PASCAL__Permissions.UPDATE_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> __PASCAL__Response:
    """Обновление объекта по ID.

    Args:
        obj_id: ID объекта.
        update_dto: Данные для обновления объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `__PASCAL__`.
        session: Асинхронная сессия базы данных.

    Returns:
        Обновлённый объект.
    """
    result = await service.update_object(obj_id, update_dto, user, session)
    return __PASCAL__Response(payload=result)


@router.delete(
    "/{obj_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление объекта по ID",
    description="Удаление объекта по ID",
    operation_id="delete___SNAKE__",
)
async def delete_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(permissions_to_check=[__PASCAL__Permissions.DELETE_MODEL])),
    ],
    service: ServiceDep,
    session: SessionDep,
) -> Response:
    """Удаление объекта по ID (логическое, через `is_deleted`).

    Args:
        obj_id: ID объекта.
        user: Пользователь, выполняющий запрос.
        service: Сервис бизнес-логики `__PASCAL__`.
        session: Асинхронная сессия базы данных.
    """
    await service.delete_object(obj_id, user, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
'''


ENTITY_PERMISSIONS = '''

class __PASCAL__Permissions:
    """Права на операции с сущностью `__PASCAL__`."""

    GET_MODEL = "GET___UPPER__"
    GET_LIST = "GET___UPPER___LIST"
    CREATE_MODEL = "CREATE___UPPER__"
    UPDATE_MODEL = "UPDATE___UPPER__"
    DELETE_MODEL = "DELETE___UPPER__"
'''


ENTITY_TEST = '''"""Тесты сервиса `__PASCAL__Service`."""

from py_main_lib.security.schemas import UserSecuritySchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.__SNAKE___schema import Create__PASCAL__Schema
from app.api.services.__SNAKE___service import __PASCAL__Service


class Test__PASCAL__Service:
    """Базовые тесты сервиса `__PASCAL__` (Arrange / Act / Assert)."""

    service = __PASCAL__Service()

    async def test_create_object(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
    ) -> None:
        """Объект создаётся и существует в БД."""
        # - Arrange -
        object_schema = Create__PASCAL__Schema(name="TestName")

        # - Act -
        obj = await self.service.create_object(object_schema, test_user, overridden_get_session)

        # - Assert -
        assert obj.id

        # - Clean -
        await overridden_get_session.delete(obj)
        await overridden_get_session.commit()
'''


# --- Kafka-сабскрайбер ------------------------------------------------------

SUBSCRIBER_SCHEMA = '''"""Схема Kafka-сообщения из топика `__CONST__`."""

from typing import Literal

from pydantic import BaseModel, Field

from app.brokers.template_schema import BaseMessageHeaderSchema, BaseMessageSchema


class __PASCAL__HeaderSchema(BaseMessageHeaderSchema):
    """Header для `__PASCAL__Schema`."""

    message_type: Literal["__PASCAL__.message_type"] = Field(
        description="Название типа сообщения.",
        default="__PASCAL__.message_type",
    )


class PayloadIn__PASCAL__Schema(BaseModel):
    """Payload для `__PASCAL__Schema`."""

    value: str = Field(
        description="Описание полезной нагрузки.",
    )


class __PASCAL__Schema(BaseMessageSchema):
    """Схема сообщения из топика `__CONST__`."""

    header: __PASCAL__HeaderSchema = Field(
        description="Служебный заголовок сообщения топика `__CONST__`.",
        default_factory=lambda: __PASCAL__HeaderSchema(),
    )
    payload: PayloadIn__PASCAL__Schema = Field(
        description="Полезная нагрузка сообщения топика `__CONST__`.",
    )
'''


SUBSCRIBER_SERVICE = '''"""Сервис обработки сообщения из Kafka-топика `__CONST__`."""

from app.brokers.kafka.schemas.subscriber_messages.__SNAKE___schema import __PASCAL__Schema


class __PASCAL__Service:
    """Бизнес-логика обработки сообщения `__CONST__`."""

    @staticmethod
    async def process(message: __PASCAL__Schema) -> None:
        """Обработать сообщение из топика `__CONST__`.

        TODO: реализовать бизнес-логику.
        """
        ...
'''


SUBSCRIBER_HANDLER = '''

from app.brokers.kafka.schemas.subscriber_messages.__SNAKE___schema import __PASCAL__Schema  # noqa: E402
from app.brokers.kafka.services.__SNAKE___service import __PASCAL__Service  # noqa: E402


@kafka_router.subscriber(
    KafkaSubscriberTopics.__CONST__,
    title="__CONST__",
    description="Сгенерированный subscriber для топика __CONST__.",
    **kafka_settings.subscriber_config.get_subscriber_kwargs(),
)
async def subscriber_to___SNAKE__(
    __SNAKE___message: __PASCAL__Schema,
    service: Annotated[__PASCAL__Service, Depends()],
) -> None:
    """Subscriber для топика `__CONST__`."""
    bind_broker_log_context(__SNAKE___message)

    await service.process(__SNAKE___message)
'''
