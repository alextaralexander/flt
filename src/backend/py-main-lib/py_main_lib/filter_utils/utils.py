from typing import TypeVar

from py_main_lib.filter_utils.schemas.filter_schema import (
    CustomFilterSchema,
    FilterSchema,
    SortCondition,
)


FilterDTO = TypeVar("FilterDTO", bound=CustomFilterSchema)


def get_filter_dto(body: FilterDTO) -> FilterSchema:
    """Преобразует фильтр-схемы для разных моделей в общую схему."""
    filter_dto = FilterSchema(
        filter=body.filter.model_dump(exclude_none=True, mode="json"),
        sort=[SortCondition(field=sort.field, direction=sort.direction.value) for sort in body.sort],
        pagesize=body.pageSize,
        page=body.page,
    )

    return filter_dto
