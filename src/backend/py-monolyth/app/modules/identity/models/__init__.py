"""Модели модуля `identity`: все таблицы — в схеме PostgreSQL `identity` (ADR-002)."""

from sqlalchemy.orm import DeclarativeBase

from app.core.dao.db_helpers.base import module_metadata
from app.core.kafka.inbox import processed_events_table
from app.core.kafka.jobs import jobs_table
from app.core.kafka.outbox import outbox_table
from app.core.kafka.scheduler import scheduled_runs_table


class Base(DeclarativeBase):
    """Базовый класс моделей модуля `identity` (схема `identity`)."""

    metadata = module_metadata("identity")


# Служебные таблицы доставки и заданий модуля (SYS-04-R24, R26, R29, R32).
outbox = outbox_table(Base.metadata)
processed_events = processed_events_table(Base.metadata)
jobs = jobs_table(Base.metadata)
scheduled_runs = scheduled_runs_table(Base.metadata)


# Модели модуля импортируются ниже, чтобы попасть в `Base.metadata` (Alembic, тесты);
# строки добавляет `make scaffold-entity module=identity name=<Entity>`.
