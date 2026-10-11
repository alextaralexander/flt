"""Fixture: создание и очистка `MyEntity` в тестовой БД."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dao.models import MyEntity
from tests.settings import test_settings


@pytest_asyncio.fixture
async def created_my_entity(overridden_get_session: AsyncSession) -> AsyncGenerator[MyEntity]:
    """Создание сущности в БД.

    После выполнения теста "подчищает за собой", удаляя сущность из БД.
    """
    object_to_add = MyEntity(name="TestName_FIXTURE", created_by=test_settings.TEST_USER_ID)
    overridden_get_session.add(object_to_add)
    await overridden_get_session.commit()

    yield object_to_add

    await overridden_get_session.delete(object_to_add)
    await overridden_get_session.commit()
