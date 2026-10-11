"""Фоновые задания: запись и команда через outbox, выполнение воркером, отмена (SYS-04-R29)."""

import asyncio
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.dao.caching import ModuleRedis
from app.core.kafka.envelope import JobCommand
from app.core.kafka.jobs import JobContext, JobRunner, JobService, JobStatus
from tests.core.kafka.conftest import OUTBOX_SCHEMA


pytestmark = pytest.mark.req("SYS-04-R29")

TOPIC = f"flt.{OUTBOX_SCHEMA}.jobs.reindex.v1"


async def _enqueue(maker: async_sessionmaker[AsyncSession], jobs: Table, outbox: Table) -> JobCommand[Any]:
    async with maker() as session, session.begin():
        job_id = await JobService(jobs, outbox).enqueue(session, kind="reindex", topic=TOPIC, payload={"n": 1})
    return JobCommand[dict[str, Any]](job_id=job_id, kind="reindex", payload={"n": 1}, attempt=1)


async def _job(maker: async_sessionmaker[AsyncSession], jobs: Table, command: JobCommand[Any]) -> Any:
    async with maker() as session:
        return (await session.execute(select(jobs).where(jobs.c.id == command.job_id))).one()


async def test_enqueue_writes_job_and_command(
    jobs: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Создание задания — запись `queued` и команда в outbox с ключом `job_id` в одной транзакции."""
    command = await _enqueue(session_maker, jobs, outbox)
    job = await _job(session_maker, jobs, command)
    async with session_maker() as session:
        row = (await session.execute(select(outbox))).one()
    assert (job.status, job.kind, job.payload) == (JobStatus.QUEUED, "reindex", {"n": 1})
    assert (row.topic, row.key) == (TOPIC, str(command.job_id))


async def test_runner_executes_job_with_progress_and_result(
    jobs: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession], raw_test_redis: Redis
) -> None:
    """Воркер переводит задание в `running`, пишет прогресс и результат, итог — `succeeded`."""
    command = await _enqueue(session_maker, jobs, outbox)

    async def work(context: JobContext) -> dict[str, Any]:
        await context.progress({"done": 1, "total": 2})
        return {"indexed": 2}

    runner = JobRunner(OUTBOX_SCHEMA, jobs, session_maker, ModuleRedis(OUTBOX_SCHEMA, client=raw_test_redis))
    status = await runner.run(command, work)

    job = await _job(session_maker, jobs, command)
    assert status is JobStatus.SUCCEEDED
    assert (job.status, job.result, job.progress, job.attempts) == (
        "succeeded",
        {"indexed": 2},
        {"done": 1, "total": 2},
        1,
    )


async def test_concurrent_delivery_runs_job_once(
    jobs: Table, outbox: Table, session_maker: async_sessionmaker[AsyncSession], raw_test_redis: Redis
) -> None:
    """Одна команда на двух воркерах одновременно: работа выполняется один раз (оптимистично по `version`)."""
    command = await _enqueue(session_maker, jobs, outbox)
    calls: list[int] = []

    async def work(context: JobContext) -> dict[str, Any]:
        calls.append(1)
        await asyncio.sleep(0.05)
        return {}

    runners = [
        JobRunner(OUTBOX_SCHEMA, jobs, session_maker, ModuleRedis(OUTBOX_SCHEMA, client=raw_test_redis))
        for _ in range(2)
    ]
    statuses = await asyncio.gather(*(runner.run(command, work) for runner in runners))

    assert calls == [1]
    assert statuses.count(JobStatus.SUCCEEDED) == 1
    assert statuses.count(None) == 1


async def test_failed_and_cancelled_jobs(
    jobs: Table,
    outbox: Table,
    session_maker: async_sessionmaker[AsyncSession],
    raw_test_redis: Redis,
    redis_clean: None,
) -> None:
    """Исключение — `failed` с ошибкой; отмена между шагами — `cancelled`."""
    redis = ModuleRedis(OUTBOX_SCHEMA, client=raw_test_redis)
    failing = await _enqueue(session_maker, jobs, outbox)
    cancelled = await _enqueue(session_maker, jobs, outbox)

    async def boom(context: JobContext) -> dict[str, Any]:
        raise ValueError("bad input")

    async def long_work(context: JobContext) -> dict[str, Any]:
        async with session_maker() as session, session.begin():
            await JobService(jobs, outbox).cancel(session, redis, cancelled.job_id)
        await context.checkpoint()
        raise AssertionError("checkpoint должен прервать задание")

    runner = JobRunner(OUTBOX_SCHEMA, jobs, session_maker, redis)
    assert await runner.run(failing, boom) is JobStatus.FAILED
    assert await runner.run(cancelled, long_work) is JobStatus.CANCELLED
    failed_job = await _job(session_maker, jobs, failing)
    assert failed_job.error == {"type": "ValueError", "message": "bad input"}
    assert (await _job(session_maker, jobs, cancelled)).status == "cancelled"
    assert await raw_test_redis.ttl(f"{OUTBOX_SCHEMA}:job_cancel:{cancelled.job_id}") > 0
    # Clean: модуль теста не входит в реестр, его ключи фикстура Redis считает чужими.
    await raw_test_redis.delete(f"{OUTBOX_SCHEMA}:job_cancel:{cancelled.job_id}")
