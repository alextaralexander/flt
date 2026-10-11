"""Тесты генератора идентификаторов `new_id()` (ADR-003, SYS-05-R7)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.ids import new_id


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-05-R7")]


def test_new_id_is_uuid_v7() -> None:
    """Идентификатор — UUID версии 7 (RFC 9562)."""
    # - Act -
    identifier = new_id()

    # - Assert -
    assert identifier.version == 7


def test_new_ids_are_unique_and_increasing() -> None:
    """Идентификаторы одного процесса уникальны и строго возрастают (локальность индекса)."""
    # - Act -
    identifiers = [new_id() for _ in range(1000)]

    # - Assert -
    assert len(set(identifiers)) == len(identifiers)
    assert identifiers == sorted(identifiers)


def test_new_id_embeds_current_time() -> None:
    """Старшие 48 бит — время создания в миллисекундах Unix."""
    # - Act -
    identifier = new_id()

    # - Assert -
    created_at = datetime.fromtimestamp((identifier.int >> 80) / 1000, tz=UTC)
    assert abs(datetime.now(UTC) - created_at) < timedelta(seconds=5)
