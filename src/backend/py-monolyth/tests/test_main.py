"""Тесты сборки приложений по реестру модулей: HTTP (`create_app`) и роль `worker` (`create_worker_app`)."""

from typing import Any

import pytest
from fastapi import APIRouter
from faststream.kafka import KafkaRouter, TestKafkaBroker
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData

from app.core.modules import ModuleDefinition
from app.main import ASYNCAPI_PATH, WORKER_SERVICE_PATHS, create_app, create_worker_app


pytestmark = pytest.mark.no_db

SAMPLE_TOPIC = "flt.sample_mod.sample_happened.v1"


def _sample_module(received: list[Any]) -> ModuleDefinition:
    """Модуль-образец с REST-роутером и Kafka-роутером, складывающим сообщения в `received`."""
    router = APIRouter(prefix="/api/v1/sample-mod")

    @router.get("/ping")
    async def ping() -> dict[str, str]:
        """Проверочный ресурс модуля."""
        return {"module": "sample_mod"}

    kafka_router = KafkaRouter()

    @kafka_router.subscriber(SAMPLE_TOPIC, group_id="flt.sample_mod.sample_handler")
    async def handle(message: dict[str, Any]) -> None:
        """Обработчик-проба."""
        received.append(message)

    return ModuleDefinition(
        name="sample_mod",
        metadata=MetaData(schema="sample_mod"),
        router=router,
        kafka_router=kafka_router,
    )


class TestCreateApp:
    """HTTP-приложение подключает REST-роутеры модулей и не подключает Kafka (роль `api`)."""

    async def test_module_router_is_served(self) -> None:
        """Ресурс модуля доступен по префиксу `/api/v1/<module>`."""
        # - Arrange -
        application = create_app([_sample_module([])])

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            response = await client.get("/api/v1/sample-mod/ping")

        # - Assert -
        assert response.status_code == 200
        assert response.json() == {"module": "sample_mod"}

    async def test_service_endpoints_are_served(self) -> None:
        """Служебные `/v1/health` и `/v1/ready` есть в любом наборе модулей."""
        # - Arrange -
        application = create_app([])

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            health = await client.get("/v1/health")
            ready = await client.get("/v1/ready")

        # - Assert -
        assert health.status_code == 200
        assert ready.status_code == 200


class TestCreateWorkerApp:
    """Роль `worker`: брокер с роутерами модулей и служебный HTTP (ADR-004, раздел 3.5)."""

    async def test_module_subscriber_receives_messages(self) -> None:
        """Сообщение топика модуля доходит до его обработчика через брокер воркера."""
        # - Arrange -
        received: list[Any] = []
        worker = create_worker_app([_sample_module(received)])
        broker = worker.brokers[0]

        # - Act -
        async with TestKafkaBroker(broker) as test_broker:
            await test_broker.publish({"value": 1}, SAMPLE_TOPIC)

        # - Assert -
        assert received == [{"value": 1}]

    @pytest.mark.parametrize("path", WORKER_SERVICE_PATHS)
    async def test_service_paths_are_served(self, path: str) -> None:
        """`/v1/health`, `/v1/ready`, `/v1/metrics` отвечают на служебном порту воркера."""
        # - Arrange -
        worker = create_worker_app([])

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=worker), base_url="http://test") as client:
            response = await client.get(path)

        # - Assert -
        assert response.status_code == 200

    async def test_asyncapi_is_served(self) -> None:
        """AsyncAPI брокера отдаётся по `/asyncapi/kafka` и содержит топики модулей."""
        # - Arrange -
        worker = create_worker_app([_sample_module([])])

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=worker), base_url="http://test") as client:
            response = await client.get(ASYNCAPI_PATH)

        # - Assert -
        assert response.status_code == 200
        assert SAMPLE_TOPIC in worker.schema.to_specification().to_json()
