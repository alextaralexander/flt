"""Тесты REST-эндпоинтов `MyEntity` через HTTP-клиент."""

from httpx import AsyncClient
from py_main_lib.filter_utils.schemas.filter_schema import FilterSchema

from app.api.schemas.my_entity_schema import (
    CreateMyEntitySchema,
    MyEntityResponse,
    UpdateMyEntitySchema,
)
from app.core.dao.models import MyEntity


class TestMyEntityController:
    """Класс с тестами для проверки работы API контроллера MyEntityController.

    :param router_url: URL по которому будут отправлять requests.

    Структура тестов представляет собой Act-Arrange-Assert. Данный шаблон организации тестов имеет:
    - `# - Arrange`, здесь создаются все необходимые данные, объекты или условия, необходимые для теста.
    - `# - Act -`, здесь выполняется тестируемая операция, их может быть несколько.
    - `# - Assert -`, здесь проверяется, соответствует ли результат ожидаемым значениям.
    - (Дополнительно) `# - Clean -`, здесь удаляем объекты из БД, чтобы не влияли на другие тесты.

    Примечание.
    Это является лишь шаблоном базовых тестов. В реальном проекте тестов должно быть больше.
    """

    router_url = "/v1/my_entity/"

    async def test_create_object(self, client: AsyncClient) -> None:
        """Тест api_route `create_object`.

        Проверки:
        - Корректный статус код.
        """
        # - Arrange -
        body = CreateMyEntitySchema(name="TestEntity")

        # - Act -
        response = await client.post(
            url=self.router_url,
            json=body.model_dump(),
        )
        # - Assert -
        assert response.status_code == 201

        # - Clean -
        response_schema = MyEntityResponse(**response.json())
        await client.delete(f"{self.router_url}{response_schema.payload.id}")

    async def test_get_object(self, client: AsyncClient, created_my_entity: MyEntity) -> None:
        """Тест api_route `get_object`.

        Перед тестовом создается `MyEntity`.

        Проверки:
        - Корректный статус код.
        - В ответе пришел нужный объект.
        """
        # - Arrange -
        url = self.router_url + str(created_my_entity.id)

        # - Act -
        response = await client.get(url)

        # - Assert -
        assert response.status_code == 200
        response_schema = MyEntityResponse(**response.json())
        assert response_schema.payload.id == created_my_entity.id

    async def test_update_object(self, client: AsyncClient, created_my_entity: MyEntity) -> None:
        """Тест api_route `update_object`.

        Перед тестовом создается `MyEntity`.

        Проверки:
        - Корректный статус код.
        - В ответе пришел обновленный объект.
        """
        # - Arrange -
        url = self.router_url + str(created_my_entity.id)
        new_value = "TestNewValue"
        body = UpdateMyEntitySchema(name=new_value)

        # - Act -
        response = await client.put(url, json=body.model_dump())

        # - Assert -
        assert response.status_code == 200
        response_schema = MyEntityResponse(**response.json())
        assert response_schema.payload.id == created_my_entity.id and response_schema.payload.name == new_value

    async def test_delete_object(self, client: AsyncClient, created_my_entity: MyEntity) -> None:
        """Тест api_route `delete_object`.

        Перед тестовом создается `MyEntity`.

        Проверки:
        - Корректный статус код.
        """
        # - Arrange -
        url = self.router_url + str(created_my_entity.id)

        # - Act -
        response = await client.delete(url)

        # - Assert -
        assert response.status_code == 204

    async def test_filter_object(self, client: AsyncClient) -> None:
        """Тест api_route `filter_object`.

        Проверки:
        - Корректный статус код.
        """
        # - Arrange -
        url = self.router_url + "filter"
        body = FilterSchema(
            filter={},
            sort=[],
            pagesize=0,
            page=0,
        )

        # - Act -
        response = await client.post(url, json=body.model_dump())

        # - Assert -
        assert response.status_code == 200
