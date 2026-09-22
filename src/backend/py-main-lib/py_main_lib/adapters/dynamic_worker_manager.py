"""
Dynamic Worker Manager для адаптивного масштабирования воркеров.

Масштабирует количество параллельных воркеров в зависимости от:
- Текущей нагрузки (queue size)
- Успешности операций (error rate)
- Throttling при приближении к лимитам
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, List, Optional


logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """Состояние worker manager."""

    NORMAL = "normal"
    SCALING_UP = "scaling_up"
    SCALING_DOWN = "scaling_down"
    THROTTLED = "throttled"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class WorkerStats:
    """Статистика воркеров за период."""

    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_time: float = 0.0
    window_start: float = field(default_factory=time.perf_counter)

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 1.0
        return self.completed_tasks / self.total_tasks

    @property
    def error_rate(self) -> float:
        return 1.0 - self.success_rate

    @property
    def avg_task_time(self) -> float:
        if self.completed_tasks == 0:
            return 0.0
        return self.total_time / self.completed_tasks

    def reset(self):
        """Сбрасывает статистику для нового окна."""
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.total_time = 0.0
        self.window_start = time.perf_counter()


@dataclass
class ScalingConfig:
    """Конфигурация масштабирования."""

    min_workers: int = 1
    max_workers: int = 20
    initial_workers: int = 5

    # Scaling triggers
    scale_up_queue_threshold: int = 10  # Scale up if queue > this
    scale_down_queue_threshold: int = 2  # Scale down if queue < this

    # Error rate thresholds
    error_rate_throttle: float = 0.3  # Throttle if error rate > 30%
    error_rate_circuit_break: float = 0.5  # Open circuit if > 50%

    # Throttling
    throttle_delay: float = 0.5  # Delay between tasks when throttled

    # Cooldowns
    scale_up_cooldown: float = 5.0  # Seconds between scale ups
    scale_down_cooldown: float = 10.0  # Seconds between scale downs

    # Stats window
    stats_window: float = 30.0  # Seconds for stats aggregation


class DynamicWorkerManager:
    """Динамический менеджер воркеров с адаптивным масштабированием."""

    def __init__(
        self,
        process_callback: Callable[[Any], Coroutine[Any, Any, Any]],
        config: Optional[ScalingConfig] = None,
        name: str = "workers",
    ):
        self.process_callback = process_callback
        self.config = config or ScalingConfig()
        self.name = name

        # State
        self._state = WorkerState.NORMAL
        self._current_workers = self.config.initial_workers
        self._semaphore = asyncio.Semaphore(self._current_workers)

        # Queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._queue_size = 0

        # Stats
        self._current_stats = WorkerStats()
        self._lifetime_stats = WorkerStats()

        # Cooldown tracking
        self._last_scale_up = 0.0
        self._last_scale_down = 0.0

        # Workers
        self._worker_tasks: List[asyncio.Task] = []
        self._running = False

        logger.info(
            "[%s] Init: workers=%d (min=%d, max=%d)",
            self.name,
            self._current_workers,
            self.config.min_workers,
            self.config.max_workers,
        )

    @property
    def state(self) -> WorkerState:
        return self._state

    @property
    def current_workers(self) -> int:
        return self._current_workers

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Запускает worker pool."""
        self._running = True
        self._start_workers(self._current_workers)

        # Start monitoring task
        self._monitor_task = asyncio.create_task(
            self._monitoring_loop(),
            name=f"{self.name}_monitor",
        )

        logger.info("[%s] Started with %d workers", self.name, self._current_workers)

    async def stop(self):
        """Останавливает workers и ждёт завершения очереди."""
        self._running = False

        # Wait for queue to drain
        if self._queue.qsize() > 0:
            logger.info(
                "[%s] Waiting for %d items in queue",
                self.name,
                self._queue.qsize(),
            )
            await self._queue.join()

        # Cancel workers
        for task in self._worker_tasks:
            task.cancel()

        await asyncio.gather(*self._worker_tasks, return_exceptions=True)

        # Cancel monitor
        if hasattr(self, "_monitor_task"):
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Log final stats
        stats = self._lifetime_stats
        logger.info(
            "[%s] Stopped: tasks=%d, success=%.1f%%, avg_time=%.3fs",
            self.name,
            stats.total_tasks,
            stats.success_rate * 100,
            stats.avg_task_time,
        )

    async def submit(self, item: Any) -> None:
        """Добавляет задачу в очередь."""
        await self._queue.put(item)

    def submit_nowait(self, item: Any) -> None:
        """Добавляет задачу без ожидания."""
        self._queue.put_nowait(item)

    def _start_workers(self, count: int):
        """Запускает указанное количество воркеров."""
        for i in range(count):
            task = asyncio.create_task(
                self._worker_loop(i),
                name=f"{self.name}_worker_{i}",
            )
            self._worker_tasks.append(task)

    async def _worker_loop(self, worker_id: int):
        """Основной цикл воркера."""
        while self._running:
            try:
                # Get task with timeout to allow graceful shutdown
                try:
                    item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Apply throttling delay if needed
                if self._state == WorkerState.THROTTLED:
                    await asyncio.sleep(self.config.throttle_delay)

                # Process with semaphore
                async with self._semaphore:
                    start = time.perf_counter()
                    success = False

                    try:
                        if self._state == WorkerState.CIRCUIT_OPEN:
                            raise RuntimeError("Circuit breaker is open")

                        await self.process_callback(item)
                        success = True

                    except Exception as e:
                        logger.error("[%s] Worker %d failed: %s", self.name, worker_id, e)

                    finally:
                        elapsed = time.perf_counter() - start
                        self._record_task(success, elapsed)
                        self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[%s] Worker %d unexpected error: %s", self.name, worker_id, e)

    def _record_task(self, success: bool, elapsed: float):
        """Записывает результат задачи в статистику."""
        # Current window stats
        self._current_stats.total_tasks += 1
        if success:
            self._current_stats.completed_tasks += 1
            self._current_stats.total_time += elapsed
        else:
            self._current_stats.failed_tasks += 1

        # Lifetime stats
        self._lifetime_stats.total_tasks += 1
        if success:
            self._lifetime_stats.completed_tasks += 1
            self._lifetime_stats.total_time += elapsed
        else:
            self._lifetime_stats.failed_tasks += 1

    async def _monitoring_loop(self):
        """Фоновый мониторинг для scaling decisions."""
        while self._running:
            await asyncio.sleep(2.0)  # Check every 2 seconds

            # Check if stats window expired
            if time.perf_counter() - self._current_stats.window_start > self.config.stats_window:
                self._evaluate_scaling()
                self._current_stats.reset()

    def _evaluate_scaling(self):
        """Оценивает необходимость масштабирования."""
        stats = self._current_stats
        queue_size = self._queue.qsize()
        now = time.perf_counter()

        # Check for circuit breaker
        if stats.error_rate >= self.config.error_rate_circuit_break and stats.total_tasks >= 5:
            if self._state != WorkerState.CIRCUIT_OPEN:
                logger.warning(
                    "[%s] CIRCUIT OPEN: error_rate=%.1f%%",
                    self.name,
                    stats.error_rate * 100,
                )
                self._state = WorkerState.CIRCUIT_OPEN
            return

        # Check for throttling
        if stats.error_rate >= self.config.error_rate_throttle and stats.total_tasks >= 5:
            if self._state != WorkerState.THROTTLED:
                logger.warning(
                    "[%s] THROTTLED: error_rate=%.1f%%",
                    self.name,
                    stats.error_rate * 100,
                )
                self._state = WorkerState.THROTTLED
            return

        # Reset state if errors recovered
        if self._state in (WorkerState.THROTTLED, WorkerState.CIRCUIT_OPEN):
            if stats.error_rate < self.config.error_rate_throttle:
                logger.info("[%s] Recovered from %s", self.name, self._state.value)
                self._state = WorkerState.NORMAL

        # Scale up if queue is growing
        if queue_size > self.config.scale_up_queue_threshold:
            if now - self._last_scale_up > self.config.scale_up_cooldown:
                self._scale_up()

        # Scale down if queue is empty
        elif queue_size < self.config.scale_down_queue_threshold:
            if now - self._last_scale_down > self.config.scale_down_cooldown:
                self._scale_down()

    def _scale_up(self):
        """Увеличивает количество воркеров."""
        if self._current_workers >= self.config.max_workers:
            return

        old = self._current_workers
        new = min(self._current_workers + 2, self.config.max_workers)
        delta = new - old

        self._current_workers = new
        self._semaphore = asyncio.Semaphore(new)
        self._start_workers(delta)
        self._last_scale_up = time.perf_counter()
        self._state = WorkerState.SCALING_UP

        logger.info(
            "[%s] SCALE UP: %d → %d workers (queue=%d)",
            self.name,
            old,
            new,
            self._queue.qsize(),
        )

    def _scale_down(self):
        """Уменьшает количество воркеров."""
        if self._current_workers <= self.config.min_workers:
            return

        old = self._current_workers
        new = max(self._current_workers - 1, self.config.min_workers)

        self._current_workers = new
        self._semaphore = asyncio.Semaphore(new)
        self._last_scale_down = time.perf_counter()
        self._state = WorkerState.SCALING_DOWN

        logger.info(
            "[%s] SCALE DOWN: %d → %d workers (queue=%d)",
            self.name,
            old,
            new,
            self._queue.qsize(),
        )

    def reset_circuit_breaker(self):
        """Сбрасывает circuit breaker вручную."""
        if self._state == WorkerState.CIRCUIT_OPEN:
            logger.info("[%s] Circuit breaker reset manually", self.name)
            self._state = WorkerState.NORMAL
            self._current_stats.reset()

    def get_stats(self) -> dict:
        """Возвращает текущую статистику."""
        return {
            "state": self._state.value,
            "current_workers": self._current_workers,
            "queue_size": self._queue.qsize(),
            "window": {
                "total": self._current_stats.total_tasks,
                "success_rate": f"{self._current_stats.success_rate:.1%}",
                "avg_time": f"{self._current_stats.avg_task_time:.3f}s",
            },
            "lifetime": {
                "total": self._lifetime_stats.total_tasks,
                "success_rate": f"{self._lifetime_stats.success_rate:.1%}",
                "avg_time": f"{self._lifetime_stats.avg_task_time:.3f}s",
            },
        }
