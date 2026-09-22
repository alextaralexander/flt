"""Структурированное логирование (structlog + OpenSearch).

Публичный интерфейс пакета:
- `logger_settings.setup_logging()` — конфигурация логирования (вызывается на старте);
- `app_logger`, `bind_log_context`, `bind_broker_log_context` — контекст логов.
"""

from app.core.logging.config import LoggerConfig, logger_settings
from app.core.logging.context import app_logger, bind_broker_log_context, bind_log_context


__all__ = (
    "LoggerConfig",
    "app_logger",
    "bind_broker_log_context",
    "bind_log_context",
    "logger_settings",
)
