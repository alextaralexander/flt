import math
from decimal import Decimal
from inspect import signature
from typing import Dict, List, Tuple, Type, Union

from sqlalchemy import Select, func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta, Query

from py_main_lib.dao.base_dao import BaseDAO
from py_main_lib.filter_utils.entity_filters import EntityFilter
from py_main_lib.filter_utils.schemas.filter_schema import (
    BaseFilterCondition,
    CustomFilterFuncType,
    FilterFuncType,
    Pagination,
)
from py_main_lib.security.schemas import UserSecuritySchema


class CustomEntityFilter(EntityFilter):
    def __init__(
        self,
        repo: BaseDAO,
        filter_fields_conditions: Dict[str, Union[FilterFuncType, CustomFilterFuncType]],
        sort_fields: Union[Tuple[str, ...], Tuple[()]],
        user: UserSecuritySchema,
        base_filter_conditions: List[BaseFilterCondition] | None = None,
        begin_query: Union[Query, None] = None,
        model: Type[DeclarativeMeta] | None = None,
        pagination_schema: Type[Pagination] = Pagination,
    ):
        super().__init__(repo, filter_fields_conditions, sort_fields, base_filter_conditions, begin_query, model)
        self.pagination_schema = pagination_schema
        self.user = user

    async def _pagination(
        self, page: int, page_size: int | None, query: Select, session: AsyncSession, pagination_mode: str
    ) -> Pagination:
        """Реализует пагинацию отсортированной query."""
        offset_value = page * page_size if page_size else 0
        total = await session.execute(select(func.count()).select_from(query))
        total = total.scalar()
        if page_size:
            query = query.limit(page_size).offset(offset_value)
        result = await session.execute(query)
        if pagination_mode == "fetch_all":
            try:
                objects = result.fetchall()
            except InvalidRequestError:
                objects = result.unique().fetchall()
        else:
            try:
                objects = result.scalars().all()
            except InvalidRequestError:
                objects = result.unique().scalars().all()
        total_pages = int(math.ceil(total / float(page_size))) if page_size else 1
        return self.pagination_schema(objects=objects, total=total, total_pages=total_pages, page=page)

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
            field_names = set(condition.field for condition in self.base_filter_conditions)
        if filter_:
            for field, value in filter_.items():
                if field not in self.filter_fields_conditions.keys() or (
                    self.base_filter_conditions and field in field_names
                ):
                    raise Exception(f'Unavailable filter field: "filter_field": {field}')

                expected_params = ["model", "query", "field", "values", "user"]
                actual_params = list(signature(self.filter_fields_conditions[field]).parameters.keys())

                if actual_params == expected_params:
                    query = self.filter_fields_conditions[field](self.model, query, field, value, self.user)
                else:
                    query = self.filter_fields_conditions[field](self.model, query, field, value)

        return query
