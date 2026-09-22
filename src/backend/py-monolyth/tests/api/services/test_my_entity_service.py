"""Тесты сервиса `MyEntityService` на реальной БД."""

from py_main_lib.filter_utils.schemas.filter_schema import FilterSchema
from py_main_lib.security.schemas import UserSecuritySchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.my_entity_schema import CreateMyEntitySchema, UpdateMyEntitySchema
from app.api.services.my_entity_service import MyEntityService
from app.core.dao.models import MyEntity


class TestMyEntityService:
    """Класс с тестами для проверки работы сервиса для MyEntity.

    Структура тестов представляет собой Act-Arrange-Assert. Данный шаблон организации тестов имеет:
    - `# - Arrange`, здесь создаются все необходимые данные, объекты или условия, необходимые для теста.
    - `# - Act -`, здесь выполняется тестируемая операция, их может быть несколько.
    - `# - Assert -`, здесь проверяется, соответствует ли результат ожидаемым значениям.
    - (Дополнительно) `# - Clean -`, здесь удаляем объекты из БД, чтобы не влияли на другие тесты.

    Примечание.
    Это является лишь шаблоном базовых тестов. В реальном проекте тестов должно быть больше.
    """

    service = MyEntityService()

    async def test_create_object(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
    ) -> None:
        """Тест service `create_object`.

        Проверки:
        - Объект существует в БД.
        """
        # - Arrange -
        test_name = "TestName"
        object_schema = CreateMyEntitySchema(name=test_name)

        # - Act -
        obj = await self.service.create_object(object_schema, test_user, overridden_get_session)

        #  - Assert -
        assert obj.id

        # - Clean -
        await overridden_get_session.delete(obj)
        await overridden_get_session.commit()

    async def test_get_object_by_id(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
        created_my_entity: MyEntity,
    ) -> None:
        """Тест service `get_object_by_id`.
        Перед тестовом создается `MyEntity`.

        Проверки:
        - Соответствует ли найденный объект.
        """
        # - Arrange -
        ...

        # - Act -
        result = await self.service.get_object_by_id(created_my_entity.id, test_user, overridden_get_session)

        # - Assert -
        assert result == created_my_entity

    async def test_update_object(
        self,
        overridden_get_session: AsyncSession,
        created_my_entity: MyEntity,
        test_user: UserSecuritySchema,
    ) -> None:
        """Тест service `update_object`.
        Перед тестовом создается `MyEntity`.

        Проверки:
        - Обновился ли объект.
        """
        # - Arrange -
        new_value = "TestNewValue"
        update_schema = UpdateMyEntitySchema(name=new_value)

        # - Act -
        updated_object = await self.service.update_object(
            created_my_entity.id,
            update_schema,
            test_user,
            overridden_get_session,
        )

        # - Assert -
        assert updated_object.id == updated_object.id and updated_object.name == update_schema.name

    async def test_delete_object(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
        created_my_entity: MyEntity,
    ) -> None:
        """Тест service `delete_object`.
        Перед тестовом создается `MyEntity`.

        Проверки:
        - Помечен ли объект как `is_deleted`.
        """
        # - Arrange -
        ...

        # - Act -
        await self.service.delete_object(created_my_entity.id, test_user, overridden_get_session)

        # - Assert -
        assert created_my_entity.is_deleted is True

    async def test_filter_object(
        self,
        overridden_get_session: AsyncSession,
        test_user: UserSecuritySchema,
        created_my_entity: MyEntity,
    ) -> None:
        """Тест service `get_objects_filtered`.
        Перед тестовом создается `MyEntity`.

        Проверки:
        - Найден ли объект.
        """
        # - Arrange -
        filter_schema = FilterSchema(
            filter={},
            sort=[],
            pagesize=0,
            page=0,
        )

        # - Act -
        filtered_object = await self.service.get_objects_filtered(filter_schema, test_user, overridden_get_session)

        # - Assert -
        assert filtered_object.elements_count == 1
