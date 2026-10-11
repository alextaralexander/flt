"""Шаблоны генерируемого кода модулей (ADR-002, раздел 3.7).

Токены подставляются простым `str.replace`, чтобы не экранировать фигурные скобки Python-кода:
- модуль: `__MODULE__` (snake_case), `__MODULE_PASCAL__`, `__MODULE_UPPER__`, `__MODULE_KEBAB__`;
- сущность: `__PASCAL__`, `__SNAKE__`, `__KEBAB__`;
- топик: `__CONST__`, `__VALUE__`, `__PASCAL__`, `__SNAKE__`.
"""


def render(template: str, **tokens: str) -> str:
    """Подставить токены вида `__NAME__` в шаблон.

    Длинные токены подставляются раньше коротких, чтобы `__MODULE_UPPER__`
    не задевался заменой `__MODULE__`.

    Args:
        template: Текст шаблона с токенами.
        **tokens: Пары `NAME=value` (ключ — без подчёркиваний-обрамления).

    Returns:
        Готовый текст.
    """
    result = template
    for key in sorted(tokens, key=len, reverse=True):
        result = result.replace(f"__{key}__", tokens[key])
    return result


# --- Модуль -----------------------------------------------------------------

MODULE_INIT = '''"""Доменный модуль `__MODULE__` (спецификация — Analytics/Specs/__MODULE__/_module.md).

Другие модули импортируют только `app.modules.__MODULE__.public` (ADR-002).
"""
'''


MODULE_DEFINITION = '''"""Описание модуля `__MODULE__` для shared kernel (ADR-002, раздел 3.2)."""

from app.core.modules import ModuleDefinition
from app.modules.__MODULE__.api.router import router
from app.modules.__MODULE__.models import Base, outbox
from app.modules.__MODULE__.permissions import module_permissions
from app.modules.__MODULE__.public.topics import TOPICS
from app.modules.__MODULE__.settings import __MODULE_PASCAL__Settings


module = ModuleDefinition(
    name="__MODULE__",
    metadata=Base.metadata,
    router=router,
    settings=__MODULE_PASCAL__Settings(),
    permissions=module_permissions(),
    topics=TOPICS,
    outbox=outbox,
)
'''


MODULE_PUBLIC_INIT = '''"""Публичный API модуля `__MODULE__`: единственное, что импортируют другие модули (ADR-002).

Сюда реэкспортируются `Protocol` сервисов и фабрики для `Depends()` (`interfaces.py`),
Pydantic-схемы (`schemas.py`), доменные события (`events.py`), ошибки (`errors.py`)
и декларации топиков (`topics.py`). Модели SQLAlchemy и репозитории не реэкспортируются.
"""
'''


MODULE_MODELS_INIT = '''"""Модели модуля `__MODULE__`: все таблицы — в схеме PostgreSQL `__MODULE__` (ADR-002)."""

from sqlalchemy.orm import DeclarativeBase

from app.core.dao.db_helpers.base import module_metadata
from app.core.kafka.inbox import processed_events_table
from app.core.kafka.jobs import jobs_table
from app.core.kafka.outbox import outbox_table
from app.core.kafka.scheduler import scheduled_runs_table


class Base(DeclarativeBase):
    """Базовый класс моделей модуля `__MODULE__` (схема `__MODULE__`)."""

    metadata = module_metadata("__MODULE__")


# Служебные таблицы доставки и заданий модуля (SYS-04-R24, R26, R29, R32).
outbox = outbox_table(Base.metadata)
processed_events = processed_events_table(Base.metadata)
jobs = jobs_table(Base.metadata)
scheduled_runs = scheduled_runs_table(Base.metadata)


# Модели модуля импортируются ниже, чтобы попасть в `Base.metadata` (Alembic, тесты);
# строки добавляет `make scaffold-entity module=__MODULE__ name=<Entity>`.
'''


MODULE_SETTINGS = '''"""Настройки модуля `__MODULE__` (ADR-002, раздел 3.3).

Префикс переменных — `__MODULE_UPPER___`, файл стенда — `envs/<стенд>/__MODULE___<стенд>.env`.
Секреты — поля `SecretStr` без значения по умолчанию, только из переменных окружения (ADR-013).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file


class __MODULE_PASCAL__Settings(BaseSettings):
    """Настройки модуля `__MODULE__`."""

    model_config = SettingsConfigDict(
        env_prefix="__MODULE_UPPER___",
        env_file=stand_env_file("__MODULE__"),
        extra="ignore",
    )
'''


MODULE_PERMISSIONS = '''"""Права модуля `__MODULE__`: коды `__MODULE__:<resource>:<action>` (SYS-06, ADR-002).

Классы `<Resource>Permissions` добавляет `make scaffold-entity module=__MODULE__ name=<Entity>` (ниже).
"""

import sys


def module_permissions() -> tuple[str, ...]:
    """Все коды прав модуля: строковые константы классов `*Permissions` этого файла."""
    codes = {
        value
        for holder_name, holder in vars(sys.modules[__name__]).items()
        if holder_name.endswith("Permissions") and isinstance(holder, type)
        for attr, value in vars(holder).items()
        if attr.isupper() and isinstance(value, str)
    }
    return tuple(sorted(codes))
'''


MODULE_API_INIT = '''"""REST-слой модуля `__MODULE__`: роутер и контроллеры ресурсов."""
'''


MODULE_ROUTER = '''"""REST-роутер модуля `__MODULE__`: префикс `/api/v1/__MODULE_KEBAB__` (ADR-004, SYS-03)."""

from fastapi import APIRouter


router = APIRouter(prefix="/api/v1/__MODULE_KEBAB__", tags=["__MODULE__"])

# Роутеры ресурсов подключает `make scaffold-entity module=__MODULE__ name=<Entity>` (ниже).
'''


MODULE_LAYER_INIT = '''"""Слой `__LAYER__` модуля `__MODULE__`."""
'''


MODULE_ALEMBIC_SECTION = """
[__MODULE__]
script_location = app/core/dao/db_helpers/migrations
prepend_sys_path = .
path_separator = os
version_locations = app/modules/__MODULE__/migrations/versions
flt_module = __MODULE__
"""


MODULE_ENV_FILE = """# Настройки модуля __MODULE__ на стенде __STAND__ (префикс __MODULE_UPPER___, ADR-002).
# Только несекретные параметры; секреты — переменные окружения (ADR-013).
"""


MODULE_TESTS_INIT = '''"""Тесты модуля `__MODULE__` (зеркалят app/modules/__MODULE__)."""
'''


MODULE_TESTS_CONFTEST = '''"""Фикстуры тестов модуля `__MODULE__` (общие фикстуры — tests/conftest.py)."""
'''


MODULE_TESTS_PACKAGE_INIT = '''"""Тесты доменных модулей: tests/modules/<module> зеркалит app/modules/<module>."""
'''


REGISTRY = '''"""Реестр доменных модулей монолита (ADR-002, раздел 3.2).

Порядок — порядок зависимостей из карты модулей SYS-01: нижние уровни раньше.
Файл правит скаффолдер (`make scaffold-module name=<module>` дописывает модуль в конец);
место модуля в порядке подтверждается спецификацией модуля. Реестр читают
`create_app()`, роль `worker`, общий `env.py` Alembic и `python -m cli list-modules`.
"""

MODULES: tuple[str, ...] = __MODULES__
'''


IMPORTLINTER_BEGIN = "; >>> modules: contracts 1-3 (generated by `python -m cli add-module`)"
IMPORTLINTER_END = "; <<< modules"

# Контракты 1–3 ADR-002 (раздел 3.5) для модулей реестра; `__MODULES_LIST__` — модули в порядке
# реестра, `__LAYERS_LIST__` — они же сверху вниз (верхний уровень зависимостей — первым).
IMPORTLINTER_MODULE_CONTRACTS = """
; 1. Модули независимы; разрешён только публичный API соседа.
[importlinter:contract:modules-public-api-only]
name = Доменные модули независимы, кроме импортов из public
type = independence
modules =
__MODULES_LIST__
ignore_imports =
    app.modules.** -> app.modules.*.public
    app.modules.** -> app.modules.*.public.**
unmatched_ignore_imports_alerting = none

; 2. Направление зависимостей между модулями — по реестру (карта SYS-01): верхние могут
;    импортировать public нижних, но не наоборот; циклы между модулями запрещены.
[importlinter:contract:modules-dependency-order]
name = Зависимости между модулями направлены по карте модулей SYS-01
type = layers
containers =
    app.modules
layers =
__LAYERS_LIST__
exhaustive = true
exhaustive_ignores =
    registry

; 3. Слои внутри каждого модуля — как в boilerplate (отсутствующий слой допустим).
[importlinter:contract:module-internal-layers]
name = Слои внутри модуля: api и brokers -> public -> services -> dao -> models
type = layers
containers =
__CONTAINERS_LIST__
layers =
    (api) | (brokers)
    (public)
    (services)
    (dao)
    (models)
"""


# --- REST-сущность ---------------------------------------------------------

ENTITY_SCHEMA = '''"""Схемы REST-ресурса `__PASCAL__` модуля `__MODULE__`."""

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


ENTITY_MODEL = '''"""Модель `__PASCAL__` модуля `__MODULE__` (таблица `__MODULE__.__SNAKE__`)."""

from py_main_lib.entities.alchemy import BaseEntityModel
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.__MODULE__.models import Base


class __PASCAL__(BaseEntityModel, Base):
    """Сущность `__PASCAL__`; служебные колонки — `BaseEntityModel` (база `EntityBase` — этап 1 Г.4)."""

    __tablename__ = "__SNAKE__"

    name: Mapped[str] = mapped_column(String, comment="Название")
'''


ENTITY_MODEL_IMPORT = """from app.modules.__MODULE__.models.__SNAKE__ import __PASCAL__  # noqa: E402, F401
"""


ENTITY_DAO = '''"""Репозиторий `__PASCAL__` модуля `__MODULE__`."""

from py_main_lib.dao.base_dao import BaseDAO

from app.modules.__MODULE__.models.__SNAKE__ import __PASCAL__
from app.modules.__MODULE__.schemas.__SNAKE___schema import Create__PASCAL__Schema, Update__PASCAL__Schema


class __PASCAL__DAO(BaseDAO[__PASCAL__, Create__PASCAL__Schema, Update__PASCAL__Schema]):
    """Репозиторий для работы с моделью `__PASCAL__`."""

    model = __PASCAL__
'''


ENTITY_SERVICE = '''"""Сервис бизнес-логики `__PASCAL__` модуля `__MODULE__`."""

from typing import Any, ClassVar
from uuid import UUID

from py_main_lib.db_utils import transaction_context
from py_main_lib.filter_utils.base_compare_methods import equals, like_
from py_main_lib.security.schemas import UserSecuritySchema
from py_main_lib.services.base_crud_service import BaseService
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ModelNotFoundInDatabaseError
from app.modules.__MODULE__.dao.__SNAKE___dao import __PASCAL__DAO
from app.modules.__MODULE__.models.__SNAKE__ import __PASCAL__
from app.modules.__MODULE__.schemas.__SNAKE___schema import (
    Create__PASCAL__Schema,
    __PASCAL__Schema,
    Update__PASCAL__Schema,
)


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
            obj: __PASCAL__ | None = await self.dao.get_by_id(obj_id, session)
            if not obj:
                raise ModelNotFoundInDatabaseError(model_id=str(obj_id), model=__PASCAL__)
            if obj.is_deleted:
                raise ModelNotFoundInDatabaseError(model_id=str(obj_id), model=__PASCAL__, is_deleted=obj.is_deleted)
        return obj
'''


ENTITY_CONTROLLER = '''"""REST-контроллер ресурса `__PASCAL__` модуля `__MODULE__`."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, Security, status
from py_main_lib.filter_utils.schemas.filter_schema import FilterSchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dao.db_helpers.db_connection import get_session
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user
from app.modules.__MODULE__.permissions import __PASCAL__Permissions
from app.modules.__MODULE__.schemas.__SNAKE___schema import (
    Create__PASCAL__Schema,
    Filtered__PASCAL__Response,
    __PASCAL__Response,
    Update__PASCAL__Schema,
)
from app.modules.__MODULE__.services.__SNAKE___service import __PASCAL__Service


router = APIRouter(prefix="/__KEBAB__s", tags=["__MODULE__"])

ServiceDep = Annotated[__PASCAL__Service, Depends()]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Создание нового объекта",
    description="Создание нового объекта",
    operation_id="__MODULE___create___SNAKE__",
)
async def create_object(
    create_dto: Create__PASCAL__Schema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(__PASCAL__Permissions.CREATE_MODEL)),
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
    operation_id="__MODULE___filter___SNAKE__",
)
async def get_filtered_list(
    filter_dto: FilterSchema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(__PASCAL__Permissions.GET_LIST)),
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
    operation_id="__MODULE___get___SNAKE__",
)
async def get_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(__PASCAL__Permissions.GET_MODEL)),
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
    operation_id="__MODULE___update___SNAKE__",
)
async def update_object(
    obj_id: UUID,
    update_dto: Update__PASCAL__Schema,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(__PASCAL__Permissions.UPDATE_MODEL)),
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
    operation_id="__MODULE___delete___SNAKE__",
)
async def delete_object(
    obj_id: UUID,
    user: Annotated[
        UserSecuritySchema,
        Security(auth_user(__PASCAL__Permissions.DELETE_MODEL)),
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


ENTITY_ROUTER_INCLUDE = """
from app.modules.__MODULE__.api.__SNAKE___controller import router as __SNAKE___router  # noqa: E402


router.include_router(__SNAKE___router)
"""


ENTITY_PERMISSIONS = '''

class __PASCAL__Permissions:
    """Права на ресурс `__SNAKE__s` модуля `__MODULE__`."""

    GET_MODEL = "__MODULE__:__SNAKE__s:read"
    GET_LIST = "__MODULE__:__SNAKE__s:read"
    CREATE_MODEL = "__MODULE__:__SNAKE__s:create"
    UPDATE_MODEL = "__MODULE__:__SNAKE__s:update"
    DELETE_MODEL = "__MODULE__:__SNAKE__s:delete"
'''


ENTITY_TEST = '''"""Тесты сервиса `__PASCAL__Service` модуля `__MODULE__`."""

import pytest
from py_main_lib.security.schemas import UserSecuritySchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.__MODULE__.schemas.__SNAKE___schema import Create__PASCAL__Schema
from app.modules.__MODULE__.services.__SNAKE___service import __PASCAL__Service


# Маркер трассировки обязателен (SYS-10-R12): тесты фичи помечаются ac("<ID ТЗ>-AC<N>") её критериев.
pytestmark = pytest.mark.req("SYS-05-R7")


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

BROKERS_INIT = '''"""Kafka-слой модуля `__MODULE__`: роутер, подписчики, топики, схемы сообщений (ADR-004)."""
'''


BROKERS_ROUTER = '''"""Kafka-роутер модуля `__MODULE__`; подключается брокером в ролях `worker` и `all` (ADR-004)."""

from faststream.kafka import KafkaRouter


kafka_router = KafkaRouter()
'''


MODULE_PUBLIC_TOPICS = '''"""Топики Kafka модуля `__MODULE__` (SYS-04-R19, R21).

По декларациям роль `migrate` создаёт топики и их DLQ; консьюмеры других модулей импортируют
отсюда декларации публичных топиков. Строки добавляет `make scaffold-subscriber`.
"""

from app.core.kafka.declarations import TopicDeclaration


TOPICS: tuple[TopicDeclaration, ...] = ()
'''


TOPIC_DECLARATION = """
__CONST__ = TopicDeclaration(name="__VALUE__", kind="__KIND__", visibility="__VISIBILITY__")
TOPICS = (*TOPICS, __CONST__)
"""


BROKERS_MESSAGES_INIT = '''"""Схемы Kafka-сообщений модуля `__MODULE__`."""
'''


BROKERS_SERVICES_INIT = '''"""Обработчики сообщений Kafka модуля `__MODULE__`: разбор сообщения и вызов `services/`."""
'''


BROKERS_SUBSCRIBERS = '''"""Подписчики Kafka модуля `__MODULE__`: тонкие хендлеры, логика — в сервисах (ADR-002).

Каждый подписчик обёрнут `@idempotent_consumer`: inbox `processed_events`, ретраи и DLQ
(SYS-04-R26, R27); обработчик получает сессию транзакции и тело сообщения.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.kafka.inbox import idempotent_consumer
from app.modules.__MODULE__.brokers.router import kafka_router
from app.modules.__MODULE__.models import processed_events
'''


SUBSCRIBER_SCHEMA = '''"""Схема нагрузки (`payload` конверта) сообщения топика `__VALUE__` (SYS-04-R20)."""

from pydantic import BaseModel, ConfigDict, Field


class __PASCAL__Payload(BaseModel):
    """Нагрузка сообщения `__VALUE__`; неизвестные поля игнорируются (SYS-04-R30)."""

    model_config = ConfigDict(extra="ignore")

    value: str = Field(description="Описание полезной нагрузки.")
'''


SUBSCRIBER_SERVICE = '''"""Сервис обработки сообщения из топика `__VALUE__` модуля `__MODULE__` (слой brokers)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.__MODULE__.brokers.messages.__SNAKE___message import __PASCAL__Payload


class __PASCAL__MessageService:
    """Бизнес-логика обработки сообщения `__CONST__`."""

    async def process(self, session: AsyncSession, payload: __PASCAL__Payload) -> None:
        """Обработать сообщение из топика `__VALUE__` в транзакции inbox (`session`).

        TODO: реализовать бизнес-логику; собственные события — через `OutboxPublisher` в той же сессии.
        """
'''


# Импорты хендлера вставляются в верхний блок импортов subscribers.py (ruff их сортирует).
SUBSCRIBER_HANDLER_IMPORTS = """from app.modules.__MODULE__.brokers.messages.__SNAKE___message import __PASCAL__Payload
from app.modules.__MODULE__.brokers.services.__SNAKE___service import __PASCAL__MessageService
from app.modules.__OWNER__.public.topics import __CONST__
"""


SUBSCRIBER_HANDLER = '''

@kafka_router.subscriber(
    __CONST__.name,
    group_id="flt.__MODULE__.__SNAKE__",
    auto_offset_reset="earliest",
    title="__CONST__",
    description="Обработчик топика __VALUE__.",
)
@idempotent_consumer("__MODULE__.__SNAKE__", processed_events)
async def handle___SNAKE__(session: AsyncSession, body: dict[str, Any]) -> None:
    """Обработчик сообщений топика `__VALUE__`: разбор нагрузки и вызов сервиса."""
    payload = __PASCAL__Payload.model_validate(body.get("payload", {}))
    await __PASCAL__MessageService().process(session, payload)
'''


# Импорт subscribers регистрирует хендлеры на kafka_router модуля.
MODULE_KAFKA_IMPORTS = """from app.modules.__MODULE__.brokers import subscribers as _subscribers  # noqa: F401
from app.modules.__MODULE__.brokers.router import kafka_router
"""
