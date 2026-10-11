"""Каждый подписчик Kafka модуля обёрнут `@idempotent_consumer` (SYS-04-R26)."""

from pathlib import Path

import pytest

from tests.architecture import checks


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-04-R26")]


def test_current_tree() -> None:
    """Текущее дерево."""
    assert checks.non_idempotent_consumer_violations(checks.SERVICE_ROOT) == []


def test_violations_are_reported(tmp_path: Path) -> None:
    """Подписчик без `@idempotent_consumer` обнаруживается, обёрнутый — нет."""
    package = tmp_path / "app" / "modules" / "rogue" / "brokers"
    package.mkdir(parents=True)
    (package / "subscribers.py").write_text(
        "@kafka_router.subscriber('flt.other.x.v1', group_id='flt.rogue.bad')\n"
        "async def bad(body): ...\n\n\n"
        "@kafka_router.subscriber('flt.other.y.v1', group_id='flt.rogue.good')\n"
        "@idempotent_consumer('rogue.good', processed_events)\n"
        "async def good(session, body): ...\n",
        encoding="utf-8",
    )
    assert checks.non_idempotent_consumer_violations(tmp_path) == [
        "app/modules/rogue/brokers/subscribers.py:2: подписчик bad без @idempotent_consumer"
    ]
