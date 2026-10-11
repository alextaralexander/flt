"""Тесты Prometheus-middleware: метка endpoint — шаблон маршрута, а не сырой путь."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.metrics.metrics_middleware import REQUEST_COUNT, UNMATCHED_ENDPOINT


pytestmark = pytest.mark.req("SYS-10-R33")


def _endpoint_labels() -> set[str]:
    """Все значения метки `endpoint`, накопленные счётчиком запросов."""
    return {sample.labels["endpoint"] for metric in REQUEST_COUNT.collect() for sample in metric.samples}


class TestPrometheusMiddleware:
    """Метки метрик не включают сырые пути с ID — защита от cardinality explosion."""

    async def test_endpoint_label_is_route_template(self, client: AsyncClient) -> None:
        """GET по ID даёт метку-шаблон `/mocked_endpoint/{item_id}`, а не путь с UUID.

        Проверки:
        - В метках есть шаблон маршрута.
        - Ни одна метка не содержит сырой UUID из запроса.
        """
        # - Arrange -
        obj_id = uuid4()

        # - Act -
        response = await client.get(f"/mocked_endpoint/{obj_id}")

        # - Assert -
        assert response.status_code == 200
        endpoints = _endpoint_labels()
        assert "/mocked_endpoint/{item_id}" in endpoints
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
