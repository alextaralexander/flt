"""Декларации топиков и периодических задач модулей (SYS-04-R19, R21, R32)."""

from datetime import timedelta

import pytest

from app.core.kafka.declarations import ScheduleDeclaration, TopicDeclaration


pytestmark = pytest.mark.no_db


async def _noop() -> None:
    """Пустая задача."""


@pytest.mark.req("SYS-04-R19")
@pytest.mark.parametrize(
    ("name", "kind"),
    [("flt.identity.user_registered.v1", "event"), ("flt.llm_gateway.jobs.generate_plan.v2", "job")],
)
def test_valid_topic_names(name: str, kind: str) -> None:
    """Имена событий и команд заданий по шаблону SYS-04-R19; модуль берётся из имени."""
    declaration = TopicDeclaration(name=name, kind=kind)  # type: ignore[arg-type]
    assert declaration.module == name.split(".")[1]
    assert declaration.dlq == f"{name}.dlq"


@pytest.mark.req("SYS-04-R19")
@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("identity.user_registered.v1", "event"),
        ("flt.identity.UserRegistered.v1", "event"),
        ("flt.identity.user_registered.v0", "event"),
        ("flt.identity.jobs.extract.v1", "event"),
        ("flt.identity.user_registered.v1", "job"),
    ],
)
def test_invalid_topic_names(name: str, kind: str) -> None:
    """Имя не по шаблону или не по виду топика — ошибка объявления."""
    with pytest.raises(ValueError, match="SYS-04-R19"):
        TopicDeclaration(name=name, kind=kind)  # type: ignore[arg-type]


@pytest.mark.req("SYS-04-R21")
def test_topic_defaults_and_job_visibility() -> None:
    """По умолчанию `internal`, 6 партиций, retention 7 суток, DLQ 30 суток; задания — только `internal`."""
    declaration = TopicDeclaration(name="flt.identity.user_registered.v1")
    assert (declaration.kind, declaration.visibility, declaration.partitions) == ("event", "internal", 6)
    assert declaration.retention == timedelta(days=7)
    assert declaration.dlq_retention == timedelta(days=30)
    with pytest.raises(ValueError, match="internal"):
        TopicDeclaration(name="flt.identity.jobs.purge.v1", kind="job", visibility="public")


@pytest.mark.req("SYS-04-R32")
def test_schedule_declaration_lock_name_and_limits() -> None:
    """Блокировка `shared_kernel:lock:schedule:<module>.<task>`; `lock_ttl` до 24 ч; cron из 5 полей."""
    schedule = ScheduleDeclaration(name="purge_tokens", cron="0 3 * * *", handler=_noop, lock_ttl=timedelta(hours=1))
    assert schedule.lock_name("identity") == "shared_kernel:lock:schedule:identity.purge_tokens"
    with pytest.raises(ValueError, match="24"):
        ScheduleDeclaration(name="x", cron="* * * * *", handler=_noop, lock_ttl=timedelta(hours=25))
    with pytest.raises(ValueError, match="cron"):
        ScheduleDeclaration(name="x", cron="* * *", handler=_noop, lock_ttl=timedelta(minutes=1))
    with pytest.raises(ValueError, match="name"):
        ScheduleDeclaration(name="Purge", cron="* * * * *", handler=_noop, lock_ttl=timedelta(minutes=1))
