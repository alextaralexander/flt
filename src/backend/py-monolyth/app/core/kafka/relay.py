"""Relay outbox роли `worker`: публикация записей `<module>.outbox` в Kafka (SYS-04-R24, R25).

Один активный relay на модуль во всём кластере — под распределённой блокировкой
`shared_kernel:lock:outbox:<module>` (TTL 30 с, heartbeat-продление). Проход: выборка
неопубликованных строк `ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED`, отправка по порядку,
`published_at = now()`. Ошибка брокера увеличивает `attempts`, пишет `last_error` и прерывает
проход, чтобы не нарушить порядок событий агрегата; следующий проход повторяет. `SKIP LOCKED`
страхует от двойной публикации при потере блокировки. Без Redis relay не стартует (fail-closed).
"""

import asyncio
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Protocol, runtime_checkable

from faststream.kafka import KafkaBroker
from sqlalchemy import Table, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.dao.caching import LockNotAcquiredError, ModuleRedis, RedisUnavailableError
from app.core.logging.context import app_logger
from app.core.time import Clock


BATCH_SIZE = 100
LOCK_TTL = timedelta(seconds=30)
IDLE_PAUSE_MIN = 0.2
IDLE_PAUSE_MAX = 2.0
LOCK_RETRY_PAUSE = 1.0


@runtime_checkable
class OutboxSink(Protocol):
    """Приёмник relay: продюсер Kafka с `acks=all` и `enable.idempotence=true` (SYS-04-R24)."""

    async def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        """Отправляет сообщение; исключение означает, что сообщение не принято брокером."""
        ...


class BrokerSink:
    """Приёмник relay на брокере Kafka процесса роли `worker` (`create_broker`, `acks=all`)."""

    def __init__(self, broker: KafkaBroker) -> None:
        """Сохраняет брокер; соединение открывает lifespan роли."""
        self.broker = broker

    async def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        """Публикует сообщение с ключом и заголовками; ошибка брокера пробрасывается relay."""
        await self.broker.publish(value, topic, key=key.encode(), headers=headers)


class OutboxRelay:
    """Relay outbox одного модуля.

    Args:
        module: Имя модуля (схема outbox).
        table: Таблица outbox модуля.
        session_maker: Фабрика сессий.
        sink: Приёмник сообщений.
        redis: `ModuleRedis` с префиксом `shared_kernel` (блокировка relay).
    """

    def __init__(
        self,
        module: str,
        table: Table,
        session_maker: async_sessionmaker[AsyncSession],
        sink: OutboxSink,
        redis: ModuleRedis,
    ) -> None:
        """Сохраняет зависимости relay."""
        self.module = module
        self.table = table
        self.session_maker = session_maker
        self.sink = sink
        self.redis = redis

    async def run_once(self) -> int:
        """Один проход relay; возвращает число опубликованных сообщений."""
        published = 0
        async with self.session_maker() as session, session.begin():
            rows = (
                await session.execute(
                    select(self.table)
                    .where(self.table.c.published_at.is_(None))
                    .order_by(self.table.c.id)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                headers: Mapping[str, str] = row.headers
                try:
                    await self.sink.send(
                        row.topic, row.key, json.dumps(row.body, ensure_ascii=False).encode(), dict(headers)
                    )
                except Exception as exc:
                    await session.execute(
                        update(self.table)
                        .where(self.table.c.id == row.id)
                        .values(attempts=self.table.c.attempts + 1, last_error=f"{type(exc).__name__}: {exc}"[:2000])
                    )
                    app_logger.warning(
                        "Outbox relay: ошибка публикации", module=self.module, topic=row.topic, error=type(exc).__name__
                    )
                    break
                await session.execute(
                    update(self.table).where(self.table.c.id == row.id).values(published_at=Clock().now())
                )
                published += 1
        return published

    async def run(self, stop: asyncio.Event) -> None:
        """Цикл relay до `stop`: под блокировкой модуля выполняет проходы с паузой 0,2–2 с при простое."""
        while not stop.is_set():
            try:
                async with self.redis.locks.acquire(f"outbox:{self.module}", LOCK_TTL, heartbeat=True):
                    await self._loop(stop)
            except LockNotAcquiredError:
                await self._sleep(stop, LOCK_RETRY_PAUSE)
            except RedisUnavailableError:
                app_logger.warning("Outbox relay: Redis недоступен, relay не работает", module=self.module)
                await self._sleep(stop, LOCK_RETRY_PAUSE)

    async def _loop(self, stop: asyncio.Event) -> None:
        """Проходы relay, пока держится блокировка и не запрошена остановка."""
        pause = IDLE_PAUSE_MIN
        while not stop.is_set():
            if await self.run_once():
                pause = IDLE_PAUSE_MIN
                continue
            await self._sleep(stop, pause)
            pause = min(pause * 2, IDLE_PAUSE_MAX)

    @staticmethod
    async def _sleep(stop: asyncio.Event, seconds: float) -> None:
        """Пауза, прерываемая остановкой."""
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            return
