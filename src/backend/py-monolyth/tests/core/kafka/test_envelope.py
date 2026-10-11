"""Конверт события и команда задания (SYS-04-R20, R29, R30, R33)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from app.core.ids import new_id
from app.core.kafka.envelope import BaseEvent, EventEnvelope, JobCommand


pytestmark = pytest.mark.no_db

COMMON = Path(__file__).resolve().parents[6] / "Analytics/Specs/_system/asyncapi-common.yaml"


class UserRegisteredPayload(BaseModel):
    """Нагрузка тестового события."""

    user_id: str


class UserRegistered(BaseEvent[UserRegisteredPayload]):
    """Тестовое событие модуля `alpha`."""

    event_type: ClassVar[str] = "alpha.user_registered"
    event_version: ClassVar[int] = 1
    topic: ClassVar[str] = "flt.alpha.user_registered.v1"
    aggregate_type: ClassVar[str] = "user"


def _schema(name: str) -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["components"]["schemas"][name]  # type: ignore[no-any-return]


@pytest.mark.req("SYS-04-R20")
def test_event_builds_envelope_with_metadata() -> None:
    """`BaseEvent.envelope` заполняет конверт метаданными класса события и модулем-производителем."""
    # - Arrange -
    aggregate_id, correlation_id = new_id(), new_id()

    # - Act -
    envelope = UserRegistered(payload=UserRegisteredPayload(user_id="u1")).envelope(
        aggregate_id=aggregate_id, correlation_id=correlation_id, occurred_at=datetime(2026, 10, 11, tzinfo=UTC)
    )

    # - Assert -
    assert envelope.event_type == "alpha.user_registered"
    assert envelope.event_version == 1
    assert envelope.producer == "alpha"
    assert envelope.aggregate_type == "user"
    assert envelope.aggregate_id == aggregate_id
    assert envelope.causation_id is None
    assert envelope.actor_id is None
    assert envelope.event_id.version == 7
    assert envelope.model_dump(mode="json")["occurred_at"] == "2026-10-11T00:00:00Z"


@pytest.mark.req("SYS-04-R33")
@pytest.mark.parametrize(("model", "schema"), [(EventEnvelope, "EventEnvelope"), (JobCommand, "JobCommand")])
def test_models_match_common_asyncapi(model: type[BaseModel], schema: str) -> None:
    """Поля и обязательность моделей совпадают со схемами `asyncapi-common.yaml`."""
    expected = _schema(schema)
    actual = model.model_json_schema()
    assert set(actual["properties"]) == set(expected["properties"])
    assert set(actual.get("required", [])) == set(expected["required"])


@pytest.mark.req("SYS-04-R20")
def test_envelope_rejects_naive_time_and_bad_version() -> None:
    """`occurred_at` только с часовым поясом, `event_version` не меньше 1."""
    base = {
        "event_id": new_id(),
        "event_type": "alpha.x",
        "producer": "alpha",
        "aggregate_type": "user",
        "aggregate_id": new_id(),
        "correlation_id": new_id(),
        "causation_id": None,
        "actor_id": None,
        "payload": {},
    }
    with pytest.raises(ValidationError):
        EventEnvelope(**base, event_version=1, occurred_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        EventEnvelope(**base, event_version=0, occurred_at=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.req("SYS-04-R30")
def test_consumers_ignore_unknown_fields() -> None:
    """Конверт и команда игнорируют неизвестные поля (совместимые изменения схемы)."""
    command = JobCommand.model_validate(
        {"job_id": str(new_id()), "kind": "echo", "payload": {}, "attempt": 1, "new": 1}
    )
    assert not hasattr(command, "new")


@pytest.mark.req("SYS-04-R20")
def test_event_class_metadata_is_validated() -> None:
    """`event_type` события — `<module>.<event>`, `topic` — топик того же модуля."""
    with pytest.raises(TypeError, match="topic"):

        class Broken(BaseEvent[UserRegisteredPayload]):
            event_type: ClassVar[str] = "alpha.user_registered"
            event_version: ClassVar[int] = 1
            topic: ClassVar[str] = "flt.beta.user_registered.v1"
            aggregate_type: ClassVar[str] = "user"
