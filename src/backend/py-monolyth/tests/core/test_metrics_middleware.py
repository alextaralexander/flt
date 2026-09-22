"""Тесты Prometheus-middleware: метка endpoint — шаблон маршрута, а не сырой путь."""

from uuid import uuid4

from httpx import AsyncClient

from app.core.metrics.metrics_middleware import REQUEST_COUNT, UNMATCHED_ENDPOINT


def _endpoint_labels() -> set[str]:
    """Все значения метки `endpoint`, накопленные счётчиком запросов."""
    return {sample.labels["endpoint"] for metric in REQUEST_COUNT.collect() for sample in metric.samples}


class TestPrometheusMiddleware:
    """Метки метрик не включают сырые пути с ID — защита от cardinality explosion."""

    async def test_endpoint_label_is_route_template(self, client: AsyncClient) -> None:
        """GET по ID даёт метку-шаблон `/my_entity/{obj_id}`, а не путь с UUID.

        FastAPI кладёт в scope["route"] маршрут без префикса include_router
        (`/v1`), поэтому метка — шаблон уровня роутера сущности.

        Проверки:
        - В метках есть шаблон маршрута.
        - Ни одна метка не содержит сырой UUID из запроса.
        """
        # - Arrange -
        obj_id = uuid4()

        # - Act -
        response = await client.get(f"/v1/my_entity/{obj_id}")

        # - Assert -
        assert response.status_code == 404  # объекта нет в БД — важен сам факт маршрутизации
        endpoints = _endpoint_labels()
        assert "/my_entity/{obj_id}" in endpoints
        assert not any(str(obj_id) in endpoint for endpoint in endpoints)

    async def test_unmatched_route_is_single_series(self, client: AsyncClient) -> None:
        """Несматченные пути (404 сканеров/опечаток) схлопываются в одну серию `unmatched`."""
        # - Arrange -
        random_path = f"/scanner/{uuid4()}"

        # - Act -
        await client.get(random_path)

        # - Assert -
        endpoints = _endpoint_labels()
        assert UNMATCHED_ENDPOINT in endpoints
        assert random_path not in endpoints
