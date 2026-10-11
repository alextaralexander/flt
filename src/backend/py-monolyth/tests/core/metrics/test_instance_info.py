"""Метрики процесса: `flt_instance_info`, `flt_redis_up`, пулы (ADR-010; SYS-10-R33)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from configs.settings import settings
from configs.stands import instance_id


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R33")]


async def _metrics_text() -> str:
    """Текст `/v1/metrics` приложения роли `api`."""
    application = create_app([])
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.get("/v1/metrics")
    assert response.status_code == 200
    return response.text


async def test_instance_info_has_required_labels() -> None:
    """`flt_instance_info` содержит `instance_id`, `role`, `version`, `stand`."""
    # - Act -
    text = await _metrics_text()

    # - Assert -
    line = next(line for line in text.splitlines() if line.startswith("flt_instance_info{"))
    for label in (
        f'instance_id="{instance_id()}"',
        'role="',
        f'version="{settings.APP_VERSION}"',
        f'stand="{settings.STAND_NAME}"',
    ):
        assert label in line
    assert line.endswith(" 1.0")


async def test_redis_up_and_pool_metrics_are_exported() -> None:
    """Экспортируются `flt_redis_up` и метрики пулов PostgreSQL и Redis."""
    # - Act -
    text = await _metrics_text()

    # - Assert -
    assert "flt_redis_up 1.0" in text
    assert "# TYPE flt_db_pool_connections gauge" in text
    assert 'flt_redis_pool_connections{state="idle"}' in text
