"""Структурированное логирование (structlog, JSON в stdout — ADR-010).

Публичный интерфейс пакета:
- `logger_settings.setup_logging()` — конфигурация логирования (вызывается на старте);
- `get_logger("flt.<module>.<name>")` — логгер модуля (поле `module`);
- `app_logger`, `bind_log_context`, `bind_broker_log_context` — контекст логов;
- `redact_sensitive_keys` — процессор маскирования секретов и ПД (ADR-010).
"""

from app.core.logging.config import LoggerConfig, logger_settings
from app.core.logging.context import app_logger, bind_broker_log_context, bind_log_context, get_logger
from app.core.logging.processors import redact_sensitive_keys


__all__ = (
    "LoggerConfig",
    "app_logger",
    "bind_broker_log_context",
    "bind_log_context",
    "get_logger",
    "logger_settings",
    "redact_sensitive_keys",
)
