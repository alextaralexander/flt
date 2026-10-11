"""Таблицы `identity.users`, `credentials`, `roles`, `user_roles` на `EntityBase` (ADR-003, ADR-006; SYS-05-R18)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.core.dao.db_helpers.db_connection import get_session_maker
from app.modules.identity.models import User


pytestmark = pytest.mark.req("SYS-05-R18")


async def test_user_gets_uuid7_timestamps_and_version() -> None:
    """Новая сущность получает UUID v7, `created_at`/`updated_at` и `version = 1`; UPDATE увеличивает версию."""
    # - Arrange -
    async with get_session_maker()() as session:
        user = User(email="Learner@Example.com", display_name="Learner")
        session.add(user)
        await session.commit()

        # - Act -
        user.display_name = "Renamed"
        await session.commit()

    # - Assert -
    assert user.id.version == 7
    assert user.created_at is not None
    assert user.version == 2


async def test_email_is_case_insensitive_unique() -> None:
    """`email` — citext: второй пользователь с тем же адресом в другом регистре отклоняется."""
    # - Arrange -
    async with get_session_maker()() as session:
        session.add(User(email="dup@example.com", display_name="A"))
        await session.commit()

        # - Act / Assert -
        session.add(User(email="DUP@example.com", display_name="B"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_concurrent_update_raises_stale_data() -> None:
    """Изменение по устаревшей версии — `StaleDataError` (HTTP 409 `core.version_conflict`)."""
    # - Arrange -
    maker = get_session_maker()
    async with maker() as setup:
        user = User(email=None, display_name="Shared")
        setup.add(user)
        await setup.commit()
        user_id = user.id

    async with maker() as first, maker() as second:
        mine = (await first.execute(select(User).where(User.id == user_id))).scalar_one()
        theirs = (await second.execute(select(User).where(User.id == user_id))).scalar_one()
        mine.display_name = "First"
        await first.commit()

        # - Act / Assert -
        theirs.display_name = "Second"
        with pytest.raises(StaleDataError):
            await second.commit()
