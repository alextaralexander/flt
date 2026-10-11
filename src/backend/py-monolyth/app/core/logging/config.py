"""Конфигурация structlog: процессоры, форматтеры, интеграция с uvicorn.

Логи пишутся только в stdout (JSON при `LOG_JSON_FORMAT`); их собирает Fluent Bit (ADR-010).

Написан на основе https://gist.github.com/nymous/f138c7f06062b7c43c060bf03759c29e
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from app.core.logging.processors import (
    add_module,
    add_open_telemetry_trace_context,
    add_process_context,
    drop_color_message_key,
    drop_contextvars_keys,
    drop_kafka_processed_message_noise,
    flatten_structlog_extra,
    move_logger_to_event_prefix,
    redact_sensitive_keys,
    rename_event_key,
)
from configs.settings import settings


class LoggerConfig:
    """Настройка логирования приложения (structlog поверх stdlib logging)."""

    def __init__(self) -> None:
        """Инициализирует конфигуратор логирования."""
        self.shared_processors: list[Processor] = [
            structlog.contextvars.merge_contextvars,
            drop_contextvars_keys,
            structlog.stdlib.add_logger_name,
            add_module,
            add_process_context,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ExtraAdder(),
            flatten_structlog_extra,
            add_open_telemetry_trace_context,
            drop_kafka_processed_message_noise,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f"),
            drop_color_message_key,
            structlog.processors.StackInfoRenderer(),
        ]
        self._is_configured = False

    def pipeline(self, *, json_format: bool) -> list[Processor]:
        """Цепочка процессоров записи: общие, затем JSON-специфичные, последним — маскирование.

        Маскирование (`redact_sensitive_keys`) стоит после форматирования исключений, чтобы секреты
        не утекали и через текст traceback-а (ADR-010, раздел 3.2; SYS-02-R46).
        """
        processors = list(self.shared_processors)
        if json_format:
            # Переименовываем `event` в `message` и форматируем исключения только для JSON-логов.
            processors += [rename_event_key, structlog.processors.format_exc_info]
        return [*processors, redact_sensitive_keys]

    def setup_logging(self) -> None:
        """Настраивает логирование (идемпотентно: повторные вызовы — no-op)."""
        if self._is_configured:
            return

        self.shared_processors = self.pipeline(json_format=settings.LOG_JSON_FORMAT)

        structlog.configure(
            processors=[*self.shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # 12-factor: логи только в stdout (файлы без ротации в контейнере — антипаттерн);
        # LOG_JSON_FORMAT переключает рендер stdout-потока, сбор файлов — забота инфраструктуры.
        if settings.LOG_JSON_FORMAT:
            renderer_processors: list[Processor] = [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ]
        else:
            renderer_processors = [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                move_logger_to_event_prefix,
                structlog.dev.ConsoleRenderer(colors=False),
            ]

        console_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=self.shared_processors,
            processors=renderer_processors,
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)

        root_logger = logging.getLogger()
        root_logger.addHandler(console_handler)
        root_logger.setLevel(settings.LOG_LEVEL.upper())

        for _log in ["uvicorn", "uvicorn.error"]:
            logging.getLogger(_log).handlers.clear()
            logging.getLogger(_log).propagate = True

        logging.getLogger("uvicorn.access").handlers.clear()
        logging.getLogger("uvicorn.access").propagate = False

        # Конфигурация для SQLAlchemy (меньше шума)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

        sys.excepthook = self.handle_exception
        self._is_configured = True

    @staticmethod
    def handle_exception(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: Any) -> None:
        """Обрабатывает неожиданные исключения и логирует их."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.getLogger().error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


logger_settings = LoggerConfig()
