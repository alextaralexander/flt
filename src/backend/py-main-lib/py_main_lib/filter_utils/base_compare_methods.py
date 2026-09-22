"""Base compare methods for EntityFilter."""

from typing import Any, List, Type

from sqlalchemy import and_, or_
from sqlalchemy.orm import DeclarativeMeta, Query


def equals(model: Type[DeclarativeMeta], query: Query, field: str, values: List[Any]) -> Query:
    """Сравнение `=`."""
    if len(values) > 1:
        query = query.filter(getattr(model, field).in_(values))
    elif len(values) == 0:
        return query
    else:
        query = query.filter(getattr(model, field) == values[0])
    return query


def is__(model: Type[DeclarativeMeta], query: Query, field: str, values: List[Any]) -> Query:
    """Сравнение `is`."""
    if len(values) > 1:
        conditions = []
        for value in values:
            conditions.append(getattr(model, field).is_(value))
        query = query.filter(or_(*conditions))
    else:
        query = query.filter(getattr(model, field).is_(values[0]))
    return query


def is_not_(model: Type[DeclarativeMeta], query: Query, field: str, values: List[Any]) -> Query:
    """Сравнение `is not`.

    Используется когда часть записей с false, а часть с null.
    """
    if len(values) > 1:
        conditions = []
        for value in values:
            conditions.append(getattr(model, field).is_not(value))
        query = query.filter(and_(*conditions))
    else:
        query = query.filter(getattr(model, field).is_not(values[0]))
    return query


def like_(model: Type[DeclarativeMeta], query: Query, field: str, values: List[Any]) -> Query:
    """Сравнение `Like` (чувствительно к регистру)."""
    for value in values:
        query = query.filter(getattr(model, field).like(f"%{value}%"))
    return query


def ilike_(model: Type[DeclarativeMeta], query: Query, field: str, values: List[Any]) -> Query:
    """Сравнение `iLike` (НЕ чувствительно к регистру)."""
    for value in values:
        query = query.filter(getattr(model, field).ilike(f"%{value}%"))
    return query
