"""Тесты транзакционного поведения `MyEntityService`."""

from unittest.mock import AsyncMock, patch

from py_main_lib.security.schemas import UserSecuritySchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.my_entity_schema import CreateMyEntitySchema, UpdateMyEntitySchema
from app.api.services.my_entity_service import MyEntityService
from app.core.dao.models import MyEntity


class TestMyEntityServiceTransactional:
    """Класс с тестами для проверки сервиса MyEntity на работу в рамках одной транзакции.

    Структура тестов представляет собой Act-Arrange-Assert. Данный шаблон организации тестов имеет:
    - `# - Arrange`, здесь создаются все необходимые данные, объекты или условия, необходимые для теста.
    - `# - Act -`, здесь выполняется тестируемая операция, их может быть несколько.
    - `# - Assert -`, здесь проверяется, соответствует ли результат ожидаемым значениям.
    - (Дополнительно) `# - Clean -`, здесь удаляем объекты из БД, чтобы не влияли на другие тесты.

    Основные проверки:
    - `commit` был вызван один раз.
    - `rollback` не сработал.
    """

    service = MyEntityService()

    async def test_create_object_transactional(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
    ) -> None:
        """Тест service `create_object` на работу в рамках одной транзакции."""
        # - Arrange -
        with patch.object(self.service.dao, "create", new_callable=AsyncMock):
            mock_session = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session.rollback = AsyncMock()

            test_name = "TestName"
            object_schema = CreateMyEntitySchema(name=test_name)

            # - Act -
            await self.service.create_object(object_schema, test_user, mock_session)

            # - Assert -
            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()

    async def test_get_object_by_id_transactional(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
        created_my_entity: MyEntity,
    ) -> None:
        """Тест service `get_object_by_id` на работу в рамках одной транзакции.

        Перед тестовом создается `MyEntity`.
        """
        # - Arrange -
        with patch.object(self.service.dao, "get_by_id", new_callable=AsyncMock) as mock_get_by_id:
            mock_session = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session.rollback = AsyncMock()

            mock_get_by_id.return_value = created_my_entity

            # - Act -
            await self.service.get_object_by_id(created_my_entity.id, test_user, mock_session)

            # - Assert -
            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()

    async def test_update_object_transactional(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
        created_my_entity: MyEntity,
    ) -> None:
        """Тест service `update_object` на работу в рамках одной транзакции.

        Перед тестовом создается `MyEntity`.
        """
        # - Arrange -
        with (
            patch.object(self.service.dao, "get_by_id", new_callable=AsyncMock) as mock_get_by_id,
            patch.object(self.service.dao, "update", new_callable=AsyncMock),
        ):
            mock_get_by_id.return_value = created_my_entity
            session = AsyncMock()
            session.commit = AsyncMock()
            session.rollback = AsyncMock()

            new_value = "TestNewValue"
            update_schema = UpdateMyEntitySchema(name=new_value)

            # - Act -
            await self.service.update_object(created_my_entity.id, update_schema, test_user, session)

            # - Assert -
            session.commit.assert_called_once()
            session.rollback.assert_not_called()

    async def test_delete_object_transactional(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
        created_my_entity: MyEntity,
    ) -> None:
        """Тест service `delete_object` на работу в рамках одной транзакции.

        Перед тестовом создается `MyEntity`.
        """
        # - Arrange -
        with (
            patch.object(self.service.dao, "get_by_id", new_callable=AsyncMock) as mock_get_by_id,
            patch.object(self.service.dao, "bool_delete", new_callable=AsyncMock),
        ):
            mock_get_by_id.return_value = created_my_entity
            session = AsyncMock()
            session.commit = AsyncMock()
            session.rollback = AsyncMock()

            # - Act -
            await self.service.delete_object(created_my_entity.id, test_user, session)

            # - Assert -
            session.commit.assert_called_once()
            session.rollback.assert_not_called()
