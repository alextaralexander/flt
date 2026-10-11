"""Пагинация и сортировка коллекций (SYS-03-R12–R14).

- `parse_sort` разбирает `sort=-created_at,title` по перечню допустимых полей; `id` всегда
  добавляется последним ключом с направлением последнего поля.
- `paginate_keyset` — курсорная пагинация по умолчанию: курсор — base64url от
  `{"s": <sort>, "k": [<значения ключей>], "id": "<id>"}` последнего элемента; условие —
  keyset по ключам сортировки, без `OFFSET` и `COUNT(*)`.
- `paginate_offset` — только для административных списков роли `platform_admin` (SYS-03-R13).
"""

import base64
import binascii
import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Query
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.http.errors import InvalidCursorError, ValidationFailedError


DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
TIEBREAKER_FIELD = "id"

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT, description="Размер страницы (1–100).")]
PageCursor = Annotated[str | None, Query(description="Курсор из `next_cursor` предыдущей страницы.")]
PageOffset = Annotated[int, Query(ge=0, description="Смещение (только административные списки).")]


@dataclass(frozen=True)
class SortField:
    """Ключ сортировки: имя поля и направление."""

    name: str
    descending: bool = False

    def __str__(self) -> str:
        """Запись ключа в параметре `sort` (`-created_at`)."""
        return f"-{self.name}" if self.descending else self.name


@dataclass(frozen=True)
class SortSpec:
    """Разобранная сортировка; `fields` всегда заканчивается полем `id`."""

    fields: tuple[SortField, ...]

    @property
    def canonical(self) -> str:
        """Каноническая запись сортировки (входит в курсор и сверяется при его разборе)."""
        return ",".join(str(f) for f in self.fields)


@dataclass(frozen=True)
class KeysetPage[T]:
    """Страница курсорной пагинации: элементы и курсор следующей страницы."""

    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class OffsetPage[T]:
    """Страница пагинации по смещению: элементы, общее число, смещение и размер."""

    items: list[T]
    total: int
    offset: int
    limit: int


def _sort_error(msg: str, value: str) -> ValidationFailedError:
    """Ошибка `422` параметра `sort` в формате `RequestValidationError.errors()`."""
    return ValidationFailedError.for_field(["query", "sort"], "value_error.sort_field", msg, value=value)


def parse_sort(sort: str | None, allowed: Collection[str], default: str) -> SortSpec:
    """Разбирает параметр `sort` (SYS-03-R14).

    Args:
        sort: значение query-параметра (`-created_at,title`) или `None`.
        allowed: допустимые поля (из перечисления контракта и константы контроллера).
        default: сортировка по умолчанию (`x-flt-default-sort`).

    Returns:
        Ключи сортировки с `id` последним ключом.

    Raises:
        ValidationFailedError: пустой ключ, поле вне `allowed` или повтор поля (`422`).
    """
    raw = sort if sort else default
    fields: list[SortField] = []
    for part in raw.split(","):
        token = part.strip()
        name = token.removeprefix("-")
        if not name:
            raise _sort_error("Empty sort field", raw)
        if name not in allowed and name != TIEBREAKER_FIELD:
            raise _sort_error(f"Sorting by '{name}' is not allowed", raw)
        if any(f.name == name for f in fields):
            raise _sort_error(f"Duplicate sort field '{name}'", raw)
        fields.append(SortField(name=name, descending=token.startswith("-")))
    if fields[-1].name != TIEBREAKER_FIELD:
        if any(f.name == TIEBREAKER_FIELD for f in fields):
            raise _sort_error("'id' must be the last sort field", raw)
        fields.append(SortField(name=TIEBREAKER_FIELD, descending=fields[-1].descending))
    return SortSpec(fields=tuple(fields))


def _encode_value(value: Any) -> Any:
    """Значение ключа сортировки для курсора (JSON)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, UUID, Decimal)):
        return str(value)
    return value


def _decode_value(column: InstrumentedAttribute[Any], value: Any) -> Any:
    """Значение из курсора в тип колонки; ошибка разбора — невалидный курсор."""
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    try:
        if python_type is datetime:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError("naive datetime in cursor")
            return parsed
        if python_type is date:
            return date.fromisoformat(value)
        if python_type is UUID:
            return UUID(str(value))
        if python_type is Decimal:
            return Decimal(str(value))
        if python_type in (int, float, str, bool) and not isinstance(value, python_type):
            raise ValueError("cursor value type mismatch")
    except (TypeError, ValueError) as exc:
        raise InvalidCursorError() from exc
    return value


def encode_cursor(spec: SortSpec, item: Any) -> str:
    """Курсор по последнему элементу страницы (base64url без `=`)."""
    keys = [_encode_value(getattr(item, f.name)) for f in spec.fields[:-1]]
    payload = {"s": spec.canonical, "k": keys, "id": _encode_value(getattr(item, TIEBREAKER_FIELD))}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str, spec: SortSpec) -> tuple[list[Any], Any]:
    """Разбирает курсор и сверяет его с сортировкой.

    Returns:
        Значения ключей сортировки (без `id`) и значение `id`.

    Raises:
        InvalidCursorError: курсор не разбирается или выдан для другой сортировки (`400`).
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise InvalidCursorError() from exc
    if (
        not isinstance(payload, dict)
        or payload.get("s") != spec.canonical
        or not isinstance(payload.get("k"), list)
        or len(payload["k"]) != len(spec.fields) - 1
        or "id" not in payload
    ):
        raise InvalidCursorError()
    return list(payload["k"]), payload["id"]


def _keyset_condition(columns: Sequence[InstrumentedAttribute[Any]], spec: SortSpec, values: Sequence[Any]) -> Any:
    """Условие «строго после позиции курсора» для ключей с любыми направлениями.

    `(k1 > v1) OR (k1 = v1 AND k2 > v2) OR …`, где `>` заменяется на `<` для убывающих ключей.
    """
    alternatives: list[ColumnElement[bool]] = []
    for index, (column, sort_field) in enumerate(zip(columns, spec.fields, strict=True)):
        equal_prefix = [columns[i] == values[i] for i in range(index)]
        step = column < values[index] if sort_field.descending else column > values[index]
        alternatives.append(and_(*equal_prefix, step))
    return or_(*alternatives)


async def paginate_keyset[T](
    session: AsyncSession,
    stmt: Select[tuple[T]],
    *,
    model: type[T],
    sort: SortSpec,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> KeysetPage[T]:
    """Курсорная страница выборки сущностей (SYS-03-R12).

    Args:
        session: сессия модуля.
        stmt: выборка сущностей `select(Model).where(...)` без `ORDER BY`, `LIMIT`, `OFFSET`.
        model: класс модели; поля сортировки — его атрибуты, обязательно поле `id`.
        sort: результат `parse_sort`.
        limit: размер страницы (1–100).
        cursor: курсор предыдущей страницы.

    Returns:
        Элементы страницы и курсор следующей (или `None` на последней странице).

    Raises:
        InvalidCursorError: курсор невалиден или выдан для другой сортировки.
        ValueError: `limit` вне 1–100.
    """
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be in 1..{MAX_PAGE_LIMIT}")
    columns: list[InstrumentedAttribute[Any]] = [getattr(model, f.name) for f in sort.fields]
    if cursor is not None:
        keys, last_id = decode_cursor(cursor, sort)
        values = [_decode_value(c, v) for c, v in zip(columns, [*keys, last_id], strict=True)]
        stmt = stmt.where(_keyset_condition(columns, sort, values))
    order_by = [c.desc() if f.descending else c.asc() for c, f in zip(columns, sort.fields, strict=True)]
    rows = list((await session.scalars(stmt.order_by(*order_by).limit(limit + 1))).all())
    items = rows[:limit]
    next_cursor = encode_cursor(sort, items[-1]) if len(rows) > limit else None
    return KeysetPage(items=items, next_cursor=next_cursor)


async def paginate_offset[T](
    session: AsyncSession,
    stmt: Select[tuple[T]],
    *,
    model: type[T],
    sort: SortSpec,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> OffsetPage[T]:
    """Страница административного списка по смещению с общим числом элементов (SYS-03-R13).

    Используется только в контроллерах, доступных лишь роли `platform_admin`.

    Raises:
        ValueError: `offset < 0` или `limit` вне 1–100.
    """
    if offset < 0 or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"offset must be >= 0 and limit in 1..{MAX_PAGE_LIMIT}")
    total = int(await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    columns = [getattr(model, f.name) for f in sort.fields]
    order_by = [c.desc() if f.descending else c.asc() for c, f in zip(columns, sort.fields, strict=True)]
    rows = list((await session.scalars(stmt.order_by(*order_by).offset(offset).limit(limit))).all())
    return OffsetPage(items=rows, total=total, offset=offset, limit=limit)
