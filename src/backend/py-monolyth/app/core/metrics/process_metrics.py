"""Метрики процесса shared kernel (ADR-010; таблица метрик `Analytics/Specs/shared_kernel/_module.md`).

- `flt_instance_info{instance_id, role, version, stand}` — info-метрика инстанса (SYS-12-R21);
- `flt_redis_up` — 1, если последний `PING` Redis прошёл;
- `flt_db_pool_connections{state}` и `flt_redis_pool_connections{state}` — состояние пулов
  на момент сбора (`in_use`, `idle`), считаются коллектором без фоновых задач.
"""

from collections.abc import Callable, Iterator

from prometheus_client import REGISTRY, Gauge
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy.ext.asyncio import AsyncEngine

from configs.settings import AppRole, settings
from configs.stands import instance_id


INSTANCE_INFO = Gauge(
    "flt_instance_info",
    "Инстанс монолита: идентификатор, роль, версия, стенд",
    ["instance_id", "role", "version", "stand"],
)
REDIS_UP = Gauge("flt_redis_up", "Redis доступен по последней проверке (1/0)")


def publish_instance_info(role: AppRole) -> None:
    """Выставляет `flt_instance_info` процесса со значением 1."""
    INSTANCE_INFO.labels(
        instance_id=instance_id(), role=str(role), version=settings.APP_VERSION, stand=settings.STAND_NAME
    ).set(1)


class PoolCollector(Collector):
    """Коллектор состояния пулов PostgreSQL и Redis процесса.

    Attributes:
        engine_provider: Возвращает движок SQLAlchemy процесса или None, если он не создан.
        redis_pool_provider: Возвращает пул redis-py или None, если клиент не создан.
    """

    def __init__(
        self,
        engine_provider: Callable[[], AsyncEngine | None],
        redis_pool_provider: Callable[[], object | None],
    ) -> None:
        """Сохраняет источники пулов."""
        self.engine_provider = engine_provider
        self.redis_pool_provider = redis_pool_provider

    def collect(self) -> Iterator[GaugeMetricFamily]:
        """Метрики `flt_db_pool_connections` и `flt_redis_pool_connections` по состояниям."""
        db = GaugeMetricFamily("flt_db_pool_connections", "Соединения пула PostgreSQL процесса", labels=["state"])
        engine = self.engine_provider()
        if engine is not None:
            pool = engine.sync_engine.pool
            in_use = getattr(pool, "checkedout", lambda: 0)()
            idle = getattr(pool, "checkedin", lambda: 0)()
            db.add_metric(["in_use"], float(in_use))
            db.add_metric(["idle"], float(idle))
        yield db

        cache = GaugeMetricFamily("flt_redis_pool_connections", "Соединения пула Redis процесса", labels=["state"])
        redis_pool = self.redis_pool_provider()
        if redis_pool is not None:
            in_use_set = getattr(redis_pool, "_in_use_connections", ())
            available = getattr(redis_pool, "_available_connections", ())
            cache.add_metric(["in_use"], float(len(in_use_set)))
            cache.add_metric(["idle"], float(len(available)))
        yield cache


_pool_collector: PoolCollector | None = None


def register_pool_collector(
    engine_provider: Callable[[], AsyncEngine | None], redis_pool_provider: Callable[[], object | None]
) -> PoolCollector:
    """Регистрирует коллектор пулов в реестре Prometheus один раз на процесс."""
    global _pool_collector
    if _pool_collector is None:
        _pool_collector = PoolCollector(engine_provider, redis_pool_provider)
        REGISTRY.register(_pool_collector)
    return _pool_collector
