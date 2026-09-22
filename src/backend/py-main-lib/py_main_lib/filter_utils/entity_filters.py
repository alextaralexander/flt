"""Универсальный Entity filter для моделей."""

import math
from decimal import Decimal
from typing import Any, Dict, List, Tuple, Type, Union

from sqlalchemy import Column, Select, asc, desc, distinct, func, select
from sqlalchemy.exc import CompileError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta, Query

from py_main_lib.dao.base_dao import BaseDAO
from py_main_lib.filter_utils.base_compare_methods import is_not_
from py_main_lib.filter_utils.schemas.filter_schema import (
    BaseFilterCondition,
    FilterFuncType,
    FilterSchema,
    Pagination,
    SortCondition,
)


BASE_FILTER_CONDITIONS = [BaseFilterCondition(field="is_deleted", values=[True], func=is_not_)]


# noinspection SpellCheckingInspection
class EntityFilter:
    """Класс для фильтрации сущностей в базе данных.

    Атрибуты:
        repo (Repository): Репозиторий, через который осуществляется доступ к данным.
        model (Model): Модель базы данных, к которой применяется фильтрация.
        filter_fields_conditions (Dict[str, FilterFuncType]):
        Словарь, содержащий имена полей и соответствующие им функции фильтрации.
            Пример:
            prompt_template_filter_conditions = {
                'is_system': __is,
                'is_library': __is,
                'is_copied_from_deleted_prompt': __is,
                'combined_text': __equals
                }
        base_filter_conditions (Dict[str, BaseFilterConditionType | None]):
        Дополнительные предварительные условия фильтрации.
            Пример:
            base_filter_conditions = {
                'is_deleted': {
                    'value': [False],
                    'func': __equals
                }
            }
        sort_fields (Tuple[str]): Поля, по которым разрешено сортировать результаты.
        begin_query (Query | None): Начальный запрос, который будет модифицироваться.
         При его отсутствии начальная query будет браться из репозитория
    """

    def __init__(
        self,
        repo: BaseDAO,
        filter_fields_conditions: Dict[str, FilterFuncType],
        sort_fields: Union[Tuple[str, ...], Tuple[()]],
        base_filter_conditions: List[BaseFilterCondition] | None = None,
        begin_query: Union[Query, None] = None,
        model: Type[DeclarativeMeta] | None = None,
        logger: Any = None,
    ):
        """__init__."""
        if not repo and not model:
            raise Exception("You must define or model or repo.")
        self.repo = repo
        self.model = repo.model if repo else model
        self.filter_fields_conditions = filter_fields_conditions
        self.base_filter_conditions = base_filter_conditions
        self.sort_fields = sort_fields
        self.begin_query = begin_query
        self.logger = logger

    @staticmethod
    def get_parameters(
        body: FilterSchema,
    ) -> tuple[
        Dict[str, List[str | bool | int | float | Decimal | None]] | None,
        List[SortCondition | None] | None,
        int,
        int | None,
    ]:
        """Получение параметров из тела запроса.

        Аргументы:
            body: Словарь, содержащий параметры запроса.

        Возвращает:
            tuple: Кортеж из четырех элементов: фильтр, сортировка,
            номер страницы и размер страницы.
                - filter_: Фильтры, которые надо применить к запросу.
                - sort: Параметры сортировки.
                - page: Номер страницы.
                - page_size: Размер страницы.
        """
        filter_ = body.filter
        sort = body.sort
        page = body.page
        page_size = body.pagesize
        return filter_, sort, page, page_size

    async def filter(self, body: FilterSchema, session: AsyncSession, pagination_mode: str = "scalars") -> Pagination:
        """Функция фильтрации.

        Фильтрует, сортирует и пагинирует результаты запроса
        на основе переданных параметров.

        Аргументы:
            body: Словарь с параметрами фильтрации, сортировки и пагинации.
            Пример:
            {
              "filter": {
                "username": [
                  "Никита",
                  "Петр",
                ],
                "lastname": [
                  "Со"
                ]
                "phone": [
                  "8900"
                ]
              },
              "sort": [
                {
                  "field": "lastname",
                  "direction": "ASC"
                },
                  "field": "username",
                  "direction": "DESC"
                }
              ],
              "pageSize": 10,
              "page": 0
            }
        Возвращает:
            entities_pagination: Объект класса Pagination,
            содержащий отфильтрованные, отсортированные и
            постранично разделённые данные.
        """
        filter_, sort, page, page_size = self.get_parameters(body)
        query = self.begin_query if self.begin_query is not None else self.repo.get_select_query()
        query = self._filter(filter_, query)
        query = self._sort(sort, query)
        entities_pagination = await self._pagination(page, page_size, query, session, pagination_mode)
        return entities_pagination

    def _filter(
        self,
        filter_: dict[str, list[str | bool | int | float | Decimal | None]] | None,
        query: Query,
    ) -> Query:
        """Добавляет фильтры к стартовой query."""

        field_names = set()
        if self.base_filter_conditions:
            for condition in self.base_filter_conditions:
                query = condition.func(self.model, query, condition.field, condition.values)
            field_names = {condition.field for condition in self.base_filter_conditions}
        if filter_:
            for field, value in filter_.items():
                if field not in self.filter_fields_conditions.keys() or (
                    self.base_filter_conditions and field in field_names
                ):
                    raise Exception(f'Unavailable filter field: "filter_field": {field}')
                query = self.filter_fields_conditions[field](self.model, query, field, value)

        return query

    def _sort(self, sort: List[SortCondition | None] | None, query: Query) -> Query:
        """Добавляет сортировку к отфильтрованной query."""
        if sort:
            for sort_item in sort:
                if sort_item is None:
                    continue
                field = sort_item.field
                if field not in self.sort_fields:
                    raise Exception(f'Unavailable sort field: "sort_field": {field}')
                direction = sort_item.direction.upper()
                try:
                    attr = getattr(self.model, field)
                except AttributeError:
                    query = self._sort_by_str(field, direction, query)
                    continue
                query = self._sort_by_model_attr(attr, direction, query)
        elif self.sort_fields:
            try:
                attr = getattr(self.model, self.sort_fields[0])
            except AttributeError:
                query = self._sort_by_str(self.sort_fields[0], "ASC", query)
                return query
            query = query.order_by(attr.asc())
        return query

    @staticmethod
    def _sort_by_model_attr(attr: Column, direction: str, query: Query):
        """Сортировка по атрибуту модели."""
        if direction == "DESC":
            query = query.order_by(attr.desc())
        else:
            query = query.order_by(attr.asc())
        return query

    @staticmethod
    def _sort_by_str(field: str, direction: str, query: Query):
        """Сортировка по строке(label'у)."""
        if direction == "DESC":
            query = query.order_by(desc(field))
        else:
            query = query.order_by(asc(field))
        return query

    async def _pagination(
        self, page: int, page_size: int | None, query: Select, session: AsyncSession, pagination_mode: str
    ) -> Pagination:
        """Реализует пагинацию отсортированной query."""
        offset_value = page * page_size if page_size else 0
        try:
            subquery = query.with_only_columns(getattr(self.model, "id")).subquery()
            total = await session.execute(select(func.count(distinct(subquery.c.id))))
        except CompileError:
            total = await session.execute(select(func.count()).select_from(query))
        total = total.scalar()
        if page_size:
            query = query.limit(page_size).offset(offset_value)
        self.log_event(f"filter query - {query}")
        result = await session.execute(query)
        if pagination_mode == "fetch_all":
            try:
                objects = result.fetchall()
                self.log_event(f"pagination_mode = fetch_all; objects - {objects}")
            except InvalidRequestError:
                result = await session.execute(query)
                objects = result.unique().fetchall()
                self.log_event(f"pagination_mode (IRE) = unique, fetch_all; objects - {objects}")
        else:
            try:
                objects = result.scalars().all()
                self.log_event(f"pagination_mode = scalars; objects - {objects}")
            except InvalidRequestError:
                result = await session.execute(query)
                objects = result.unique().scalars().all()
                self.log_event(f"pagination_mode = scalars, all; objects - {objects}")
        total_pages = int(math.ceil(total / float(page_size))) if page_size else 1
        return Pagination(objects=objects, total=total, total_pages=total_pages, page=page)

    def log_event(self, message: str):
        if self.logger:
            self.logger.info(message)
