"""ModelFamily Schema."""

from decimal import Decimal
from enum import StrEnum
from typing import Any, Callable, Dict, Generic, List, Literal, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.orm import DeclarativeMeta, Query

from py_main_lib.entities.alchemy import BaseEntityModel
from py_main_lib.security.schemas import UserSecuritySchema


PM = TypeVar("PM", bound=BaseModel)

CustomFilterFuncType = Callable[[DeclarativeMeta, Query, str, List[Any], UserSecuritySchema], Query]


class FilterResult(BaseModel, Generic[PM]):
    """FilterResult."""

    page_size: int
    current_page: int
    elements_count: int
    page_count: int
    result: List[PM]


class SortCondition(BaseModel):
    field: str
    direction: Literal["asc", "ASC", "desc", "DESC"] = "ASC"


class SortDirectionEnum(StrEnum):
    """Тип сортировки при фильтрации списка данных."""

    asc = "asc"
    desc = "desc"


class FilterSchema(BaseModel):
    filter: Dict[str, List[str | bool | int | float | Decimal | None]] = Field(default_factory=lambda: dict())
    sort: List[SortCondition | None] = Field(default_factory=lambda: list())
    pagesize: int | None = Field(default=0)
    page: int = Field(default=0)


class Pagination(BaseModel):
    objects: List[BaseEntityModel]
    total: int
    total_pages: int
    page: int

    model_config = ConfigDict(arbitrary_types_allowed=True)


FilterFuncType = Callable[..., Query]
# noinspection SpellCheckingInspection
"""Фильтрует запрос на основе переданных значений.

    Аргументы:
        model (Type[Model]): Модель базы данных, которую нужно отфильтровать.
        query (SQLAlchemyQuery): Запрос, который необходимо отфильтровать.
        field_name (str): Имя поля модели, по которому производится фильтрация.
        values (list): Список значений, которые должны присутствовать в указанном поле.

    Возвращает:
        Query: Отфильтрованный запрос.
"""


class FieldFilterCondition(BaseModel):
    """Словарь, описывающий предварительную фильтрацию для определённого поля сущности.

    Аргументы:
        value - дефолтное значение для конкретного Field
        func - функция для фильтрации типа FilterFuncType
    Пример:
    {
        'value': [False],
        'func': __equals
    }
    """

    value: List[Any]
    func: FilterFuncType


class BaseFilterCondition(BaseModel):
    field: str
    values: List[Any]
    func: FilterFuncType


class FilterFieldsSchema(BaseModel):
    """Параметры для фильтрации моделей."""


class SortFieldSchema(BaseModel):
    """Параметры для сортировки моделей."""

    field: str = Field(
        description="Название поля, по которому выполняется сортировка.",
    )

    direction: SortDirectionEnum = Field(
        description="Направление сортировки.",
    )


class CustomFilterSchema(BaseModel):
    """Filter model schema."""

    filter: FilterFieldsSchema = Field(
        default=FilterFieldsSchema(),
        description="Запрос фильтрации.",
    )

    sort: List[SortFieldSchema] = Field(
        default_factory=list,
        description="Запрос сортировки.",
    )

    pageSize: int = Field(
        default=10,
        description="Запрос кол-во Script на странице.",
        validation_alias=AliasChoices("pagesize", "page_size", "pageSize"),
        alias="pagesize",
    )

    page: int = Field(
        default=0,
        description="Номер страницы.",
    )


class CustomFilterCondition(BaseFilterCondition):
    user: UserSecuritySchema
    func: CustomFilterFuncType
