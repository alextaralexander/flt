"""
File Prioritizer для интеллектуальной сегментации файлов по размеру.

Маленькие файлы (<1MB) накапливаются в батчи для эффективной обработки.
Большие файлы (>1MB) отправляются немедленно (fire-and-forget).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Generic, List, Optional, TypeVar


logger = logging.getLogger(__name__)

# 1MB threshold
DEFAULT_LARGE_FILE_THRESHOLD = 1024 * 1024
DEFAULT_BATCH_SIZE = 10
DEFAULT_BATCH_TIMEOUT = 5.0  # seconds

T = TypeVar("T")


class FilePriority(Enum):
    """Приоритет файла по размеру."""

    SMALL = "small"  # <1MB - батчевая обработка
    LARGE = "large"  # >1MB - немедленная отправка


@dataclass
class PrioritizedFile(Generic[T]):
    """Файл с определённым приоритетом."""

    data: Any  # Original file data/metadata
    size_bytes: int
    priority: FilePriority
    created_at: float = field(default_factory=time.perf_counter)

    @property
    def age_seconds(self) -> float:
        return time.perf_counter() - self.created_at


@dataclass
class BatchResult:
    """Результат обработки батча файлов."""

    processed: int = 0
    failed: int = 0
    total_bytes: int = 0
    elapsed_time: float = 0.0
    errors: List[str] = field(default_factory=list)


class FilePrioritizer:
    """
    Интеллектуальная приоритизация файлов по размеру.

    - Маленькие файлы (<threshold) накапливаются в батчи
    - Большие файлы (>threshold) обрабатываются немедленно
    - Автоматический flush батча по размеру или таймауту
    """

    def __init__(
        self,
        process_callback: Callable[[List[Any]], Coroutine[Any, Any, BatchResult]],
        large_file_threshold: int = DEFAULT_LARGE_FILE_THRESHOLD,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_timeout: float = DEFAULT_BATCH_TIMEOUT,
        fire_and_forget_large: bool = True,
    ):
        """
        Args:
            process_callback: Async функция для обработки батча файлов
            large_file_threshold: Порог размера для больших файлов (bytes)
            batch_size: Максимальный размер батча для маленьких файлов
            batch_timeout: Таймаут для flush батча (секунды)
            fire_and_forget_large: Не ждать завершения больших файлов
        """
        self.process_callback = process_callback
        self.large_file_threshold = large_file_threshold
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.fire_and_forget_large = fire_and_forget_large

        # Batch state
        self._small_files_batch: List[PrioritizedFile] = []
        self._batch_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._last_add_time = time.perf_counter()

        # Stats
        self._total_small_files = 0
        self._total_large_files = 0
        self._total_batches_flushed = 0
        self._total_bytes_processed = 0

        # Fire-and-forget tasks для tracking
        self._pending_large_tasks: List[asyncio.Task] = []

        logger.info(
            "[FilePrioritizer] Init: threshold=%s, batch_size=%d, timeout=%.1fs",
            self._format_size(large_file_threshold),
            batch_size,
            batch_timeout,
        )

    async def __aenter__(self):
        """Start background flush timer."""
        self._start_flush_timer()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Flush remaining and cleanup."""
        await self.close()

    def classify_file(self, size_bytes: int) -> FilePriority:
        """Классифицирует файл по размеру."""
        if size_bytes >= self.large_file_threshold:
            return FilePriority.LARGE
        return FilePriority.SMALL

    async def add_file(self, file_data: Any, size_bytes: int) -> Optional[BatchResult]:
        """Добавляет файл с автоматической классификацией."""
        priority = self.classify_file(size_bytes)
        prioritized: PrioritizedFile[Any] = PrioritizedFile(
            data=file_data,
            size_bytes=size_bytes,
            priority=priority,
        )

        if priority == FilePriority.LARGE:
            return await self._process_large_file(prioritized)
        else:
            return await self._add_to_batch(prioritized)

    async def _process_large_file(self, file: PrioritizedFile) -> Optional[BatchResult]:
        """Обрабатывает большой файл (немедленно или fire-and-forget)."""
        self._total_large_files += 1

        logger.debug(
            "[FilePrioritizer] Large file: %s - immediate processing",
            self._format_size(file.size_bytes),
        )

        if self.fire_and_forget_large:
            # Fire-and-forget: запускаем task и не ждём
            task = asyncio.create_task(
                self._process_single_large(file),
                name=f"large_file_{file.size_bytes}",
            )
            self._pending_large_tasks.append(task)
            # Cleanup completed tasks
            self._pending_large_tasks = [t for t in self._pending_large_tasks if not t.done()]
            return None
        else:
            # Синхронная обработка
            return await self._process_single_large(file)

    async def _process_single_large(self, file: PrioritizedFile) -> BatchResult:
        """Обрабатывает один большой файл."""
        start = time.perf_counter()
        try:
            result = await self.process_callback([file.data])
            result.elapsed_time = time.perf_counter() - start
            self._total_bytes_processed += file.size_bytes
            return result
        except Exception as e:
            logger.error("[FilePrioritizer] Large file failed: %s", e)
            return BatchResult(
                failed=1,
                elapsed_time=time.perf_counter() - start,
                errors=[str(e)],
            )

    async def _add_to_batch(self, file: PrioritizedFile) -> Optional[BatchResult]:
        """Добавляет маленький файл в батч."""
        async with self._batch_lock:
            self._small_files_batch.append(file)
            self._total_small_files += 1
            self._last_add_time = time.perf_counter()

            # Проверяем нужен ли flush по размеру
            if len(self._small_files_batch) >= self.batch_size:
                return await self._flush_batch_impl()

        return None

    async def flush(self) -> Optional[BatchResult]:
        """Принудительный flush батча."""
        async with self._batch_lock:
            if self._small_files_batch:
                return await self._flush_batch_impl()
        return None

    async def _flush_batch_impl(self) -> BatchResult:
        """Внутренняя реализация flush (вызывать под lock)."""
        if not self._small_files_batch:
            return BatchResult()

        batch = self._small_files_batch
        self._small_files_batch = []
        self._total_batches_flushed += 1

        batch_size = len(batch)
        total_bytes = sum(f.size_bytes for f in batch)

        logger.debug(
            "[FilePrioritizer] Flushing batch: %d files, %s",
            batch_size,
            self._format_size(total_bytes),
        )

        start = time.perf_counter()
        try:
            result = await self.process_callback([f.data for f in batch])
            result.elapsed_time = time.perf_counter() - start
            result.total_bytes = total_bytes
            self._total_bytes_processed += total_bytes
            return result
        except Exception as e:
            logger.error("[FilePrioritizer] Batch flush failed: %s", e)
            return BatchResult(
                failed=batch_size,
                total_bytes=total_bytes,
                elapsed_time=time.perf_counter() - start,
                errors=[str(e)],
            )

    def _start_flush_timer(self):
        """Запускает фоновый таймер для flush по таймауту."""

        async def timer_loop():
            while True:
                await asyncio.sleep(1.0)  # Check every second

                async with self._batch_lock:
                    if not self._small_files_batch:
                        continue

                    # Check oldest file age
                    oldest = min(f.created_at for f in self._small_files_batch)
                    age = time.perf_counter() - oldest

                    if age >= self.batch_timeout:
                        logger.debug(
                            "[FilePrioritizer] Timeout flush: %d files, age=%.1fs",
                            len(self._small_files_batch),
                            age,
                        )
                        await self._flush_batch_impl()

        self._flush_task = asyncio.create_task(timer_loop(), name="prioritizer_flush_timer")

    async def close(self):
        """Закрывает prioritizer, flush остатков."""
        # Stop timer
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush remaining small files
        await self.flush()

        # Wait for pending large file tasks
        if self._pending_large_tasks:
            logger.info(
                "[FilePrioritizer] Waiting for %d pending large file tasks",
                len(self._pending_large_tasks),
            )
            await asyncio.gather(*self._pending_large_tasks, return_exceptions=True)

        # Log final stats
        logger.info(
            "[FilePrioritizer] Closed: small=%d, large=%d, batches=%d, bytes=%s",
            self._total_small_files,
            self._total_large_files,
            self._total_batches_flushed,
            self._format_size(self._total_bytes_processed),
        )

    def get_stats(self) -> dict:
        """Возвращает статистику."""
        return {
            "small_files": self._total_small_files,
            "large_files": self._total_large_files,
            "batches_flushed": self._total_batches_flushed,
            "bytes_processed": self._total_bytes_processed,
            "pending_batch_size": len(self._small_files_batch),
            "pending_large_tasks": len([t for t in self._pending_large_tasks if not t.done()]),
        }

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        """Форматирует размер."""
        if bytes_val >= 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f}GB"
        elif bytes_val >= 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f}MB"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.1f}KB"
        return f"{bytes_val}B"


def segment_files_by_size(
    files: List[Any],
    get_size: Callable[[Any], int],
    threshold: int = DEFAULT_LARGE_FILE_THRESHOLD,
) -> tuple[List[Any], List[Any]]:
    """Разделяет список файлов на маленькие и большие."""
    small = []
    large = []

    for f in files:
        size = get_size(f)
        if size >= threshold:
            large.append(f)
        else:
            small.append(f)

    return small, large
