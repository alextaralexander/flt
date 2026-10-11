"""Readiness по роли и liveness с деталями (ADR-010, раздел 3.4; SYS-10-R33, SYS-11-R11)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.metrics.readiness import ReadinessProbe
from app.main import create_app, create_worker_app


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R33")]


async def _ok() -> None:
    """Проверка, которая проходит."""


async def _down() -> None:
    """Проверка недоступной зависимости."""
    raise OSError("connection refused")


class TestReadinessProbe:
    """Проверки роли и кэш результата."""

    async def test_failed_check_makes_not_ready(self) -> None:
        """Отказ одной проверки — инстанс не готов, в деталях — имя ошибки."""
        # - Arrange -
        probe = ReadinessProbe({"postgres": _down, "kafka": _ok})

        # - Act -
        result = await probe.run()

        # - Assert -
        assert result.ready is False
        assert result.checks == {"postgres": "error: OSError", "kafka": "ok"}

    async def test_result_is_cached_for_five_seconds(self) -> None:
        """В пределах 5 с проверки не повторяются; после — повторяются."""
        # - Arrange -
        calls: list[int] = []
        now = [100.0]

        async def counted() -> None:
            calls.append(1)

        probe = ReadinessProbe({"postgres": counted}, clock=lambda: now[0])

        # - Act -
        await probe.run()
        now[0] += 4.9
        await probe.run()
        now[0] += 0.2
        await probe.run()

        # - Assert -
        assert len(calls) == 2


class TestReadyEndpoint:
    """`/v1/ready`: 503 при отказе зависимости роли, Redis не учитывается."""

    async def test_api_role_checks_only_postgres(self) -> None:
        """Роль `api` проверяет PostgreSQL; Redis в readiness не входит (ADR-003)."""
        # - Act -
        application = create_app([])

        # - Assert -
        assert set(application.state.readiness.checks) == {"postgres"}

    async def test_worker_role_checks_postgres_and_kafka(self) -> None:
        """Роль `worker` проверяет PostgreSQL и Kafka."""
        # - Act -
        worker = create_worker_app([])
        service_app = dict(worker.routes)["/v1/ready"]

        # - Assert -
        assert set(service_app.state.readiness.checks) == {"postgres", "kafka"}

    async def test_unavailable_dependency_gives_503_with_details(self) -> None:
        """Недоступный PostgreSQL — 503, тело вне конверта ошибок, с деталями проверок."""
        # - Arrange -
        application = create_app([])
        application.state.readiness = ReadinessProbe({"postgres": _down})

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            response = await client.get("/v1/ready")

        # - Assert -
        assert response.status_code == 503
        payload = response.json()["payload"]
        assert payload["status"] == "not_ready"
        assert payload["checks"] == {"postgres": "error: OSError"}

    async def test_worker_without_kafka_is_not_ready(self) -> None:
        """Воркер с неподключённым брокером Kafka отвечает 503 (SYS-10-R33)."""
        # - Arrange -
        worker = create_worker_app([])

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=worker), base_url="http://test") as client:
            response = await client.get("/v1/ready")

        # - Assert -
        assert response.status_code == 503
        assert response.json()["payload"]["checks"]["kafka"].startswith("error")


class TestHealthEndpoint:
    """`/v1/health` всегда 200, Redis — информационная деталь."""

    async def test_health_reports_redis_detail(self) -> None:
        """В теле liveness есть `checks.redis`."""
        # - Arrange -
        application = create_app([])

        # - Act -
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            response = await client.get("/v1/health")

        # - Assert -
        assert response.status_code == 200
        assert response.json()["payload"]["checks"]["redis"] in {"ok", "unavailable"}
