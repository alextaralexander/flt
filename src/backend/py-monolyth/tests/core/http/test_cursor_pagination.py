"""Интеграционные тесты пагинации и сортировки на PostgreSQL (SYS-03-R12, R13, R14)."""

import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import DateTime, MetaData, String, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.http.errors import InvalidCursorError, ValidationFailedError
from app.core.http.pagination import paginate_keyset, paginate_offset, parse_sort
from configs.settings import settings


SCHEMA = "core_pagination_test"
BASE_TIME = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class Base(DeclarativeBase):
    """База тестовой модели в отдельной схеме теста."""

    metadata = MetaData(schema=SCHEMA)


class Probe(Base):
    """Тестовая сущность для пагинации."""

    __tablename__ = "probes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Сессия PostgreSQL с таблицей `core_pagination_test.probes`; схема удаляется после теста."""
    engine = create_async_engine(settings.sqlalchemy_database_uri)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    await engine.dispose()


async def _add(session: AsyncSession, title: str, minutes: int, probe_id: uuid.UUID | None = None) -> Probe:
    """Добавляет запись со временем `BASE_TIME + minutes`."""
    probe = Probe(id=probe_id or uuid.uuid4(), title=title, created_at=BASE_TIME + timedelta(minutes=minutes))
    session.add(probe)
    await session.commit()
    return probe


async def _all_pages(session: AsyncSession, sort: str, limit: int) -> list[list[str]]:
    """Все страницы выборки в виде списков заголовков."""
    spec = parse_sort(sort, allowed={"created_at", "title"}, default="-created_at")
    pages: list[list[str]] = []
    cursor = None
    while True:
        page = await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=limit, cursor=cursor)
        pages.append([p.title for p in page.items])
        cursor = page.next_cursor
        if cursor is None:
            return pages


@pytest.mark.req("SYS-03-R12")
async def test_pages_follow_sort_and_end_with_null_cursor(session: AsyncSession) -> None:
    """Страницы идут по сортировке без пропусков и повторов; последняя страница — `next_cursor = null`."""
    # - Arrange -
    for index, title in enumerate(["a", "b", "c", "d", "e"]):
        await _add(session, title, index)

    # - Act -
    pages = await _all_pages(session, "-created_at", limit=2)

    # - Assert -
    assert pages == [["e", "d"], ["c", "b"], ["a"]]


@pytest.mark.req("SYS-03-R12")
@pytest.mark.req("SYS-03-R14")
async def test_mixed_directions_and_ties(session: AsyncSession) -> None:
    """Смешанные направления (`title,-created_at`) и равные значения ключа: `id` разрешает ничьи."""
    # - Arrange -
    ids = sorted(uuid.uuid4() for _ in range(3))
    await _add(session, "x", 1, ids[0])
    await _add(session, "x", 1, ids[1])
    await _add(session, "x", 1, ids[2])
    await _add(session, "a", 5)
    await _add(session, "x", 9)

    # - Act -
    spec = parse_sort("title,-created_at", allowed={"created_at", "title"}, default="-created_at")
    first = await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=2)
    second = await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=2, cursor=first.next_cursor)
    third = await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=2, cursor=second.next_cursor)

    # - Assert -
    order = [(p.title, p.created_at, p.id) for p in first.items + second.items + third.items]
    assert [(t, c) for t, c, _ in order] == [
        ("a", BASE_TIME + timedelta(minutes=5)),
        ("x", BASE_TIME + timedelta(minutes=9)),
        ("x", BASE_TIME + timedelta(minutes=1)),
        ("x", BASE_TIME + timedelta(minutes=1)),
        ("x", BASE_TIME + timedelta(minutes=1)),
    ]
    assert [i for _, _, i in order[2:]] == sorted(ids, reverse=True)
    assert third.next_cursor is None


@pytest.mark.req("SYS-03-R12")
async def test_stable_when_rows_inserted_between_pages(session: AsyncSession) -> None:
    """Вставка нового элемента между запросами страниц не сдвигает следующие страницы."""
    # - Arrange -
    for index, title in enumerate(["a", "b", "c", "d"]):
        await _add(session, title, index)
    spec = parse_sort(None, allowed={"created_at"}, default="-created_at")
    first = await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=2)

    # - Act -
    await _add(session, "new", 100)
    second = await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=2, cursor=first.next_cursor)

    # - Assert -
    assert [p.title for p in first.items] == ["d", "c"]
    assert [p.title for p in second.items] == ["b", "a"]


@pytest.mark.req("SYS-03-R12")
async def test_cursor_format_and_where_filter(session: AsyncSession) -> None:
    """Курсор — base64url JSON `{s, k, id}`; фильтр выборки сохраняется между страницами."""
    # - Arrange -
    for index, title in enumerate(["a", "b", "skip", "c"]):
        await _add(session, title, index)
    spec = parse_sort("-created_at", allowed={"created_at"}, default="-created_at")
    stmt = select(Probe).where(Probe.title != "skip")

    # - Act -
    first = await paginate_keyset(session, stmt, model=Probe, sort=spec, limit=1)
    assert first.next_cursor is not None
    payload = json.loads(base64.urlsafe_b64decode(first.next_cursor + "=" * (-len(first.next_cursor) % 4)))
    second = await paginate_keyset(session, stmt, model=Probe, sort=spec, limit=5, cursor=first.next_cursor)

    # - Assert -
    assert "=" not in first.next_cursor
    assert payload["s"] == "-created_at,-id"
    assert payload["k"] == [(BASE_TIME + timedelta(minutes=3)).isoformat()]
    assert payload["id"] == str(first.items[0].id)
    assert [p.title for p in second.items] == ["b", "a"]


@pytest.mark.req("SYS-03-R12")
@pytest.mark.parametrize(
    "cursor",
    [
        "%%%not-base64",
        base64.urlsafe_b64encode(b"[1, 2]").decode(),
        base64.urlsafe_b64encode(b'{"s": "title,id", "k": ["x"], "id": "1"}').decode(),
        base64.urlsafe_b64encode(b'{"s": "-created_at,-id", "k": [], "id": "1"}').decode(),
        base64.urlsafe_b64encode(b'{"s": "-created_at,-id", "k": ["not a date"], "id": "1"}').decode(),
        base64.urlsafe_b64encode(b'{"s": "-created_at,-id", "k": ["2026-10-10T12:00:00"], "id": "1"}').decode(),
        base64.urlsafe_b64encode(b'{"s": "-created_at,-id", "k": ["2026-10-10T12:00:00Z"], "id": "nope"}').decode(),
    ],
)
async def test_invalid_or_foreign_cursor_rejected(session: AsyncSession, cursor: str) -> None:
    """Невалидный курсор или курсор другой сортировки — `400 core.invalid_cursor`."""
    spec = parse_sort("-created_at", allowed={"created_at", "title"}, default="-created_at")
    with pytest.raises(InvalidCursorError) as exc_info:
        await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=2, cursor=cursor)
    assert (exc_info.value.status, exc_info.value.error_code) == (400, "core.invalid_cursor")


@pytest.mark.req("SYS-03-R12")
async def test_limit_out_of_range_rejected(session: AsyncSession) -> None:
    """Размер страницы вне 1–100 отклоняется."""
    spec = parse_sort(None, allowed={"created_at"}, default="-created_at")
    with pytest.raises(ValueError, match="limit"):
        await paginate_keyset(session, select(Probe), model=Probe, sort=spec, limit=101)


@pytest.mark.req("SYS-03-R13")
async def test_offset_page_with_total(session: AsyncSession) -> None:
    """Пагинация по смещению возвращает элементы страницы, `total`, `offset`, `limit`."""
    # - Arrange -
    for index, title in enumerate(["a", "b", "c", "d", "e"]):
        await _add(session, title, index)
    spec = parse_sort("title", allowed={"title"}, default="title")

    # - Act -
    page = await paginate_offset(session, select(Probe), model=Probe, sort=spec, offset=2, limit=2)

    # - Assert -
    assert [p.title for p in page.items] == ["c", "d"]
    assert (page.total, page.offset, page.limit) == (5, 2, 2)
    with pytest.raises(ValueError, match="offset"):
        await paginate_offset(session, select(Probe), model=Probe, sort=spec, offset=-1)


@pytest.mark.no_db
@pytest.mark.req("SYS-03-R14")
def test_parse_sort() -> None:
    """`parse_sort`: сортировка по умолчанию, несколько полей, `-` — убывание, `id` последним ключом."""
    allowed = {"created_at", "title"}
    assert parse_sort(None, allowed, "-created_at").canonical == "-created_at,-id"
    assert parse_sort("title,-created_at", allowed, "-created_at").canonical == "title,-created_at,-id"
    assert parse_sort("title,id", allowed, "-created_at").canonical == "title,id"
    assert parse_sort("-id", allowed, "-created_at").canonical == "-id"


@pytest.mark.no_db
@pytest.mark.req("SYS-03-R14")
@pytest.mark.parametrize("sort", ["secret", "title,title", "title,,created_at", "id,title", "-"])
def test_parse_sort_rejects_invalid(sort: str) -> None:
    """Поле вне перечня, повтор, пустой ключ или `id` не последним — `422 core.validation_failed`."""
    with pytest.raises(ValidationFailedError) as exc_info:
        parse_sort(sort, {"created_at", "title"}, "-created_at")
    error = exc_info.value
    assert (error.status, error.error_code) == (422, "core.validation_failed")
    assert error.details["errors"][0]["loc"] == ["query", "sort"]
