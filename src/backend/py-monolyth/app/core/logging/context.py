"""Общие объекты и helper'ы для логирования."""

from __future__ import annotations

from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, unbind_contextvars


app_logger = structlog.stdlib.get_logger("app")

MANAGED_LOG_CONTEXT_KEYS = ("user_chat_id",)


def _normalize_log_context_value(value: Any) -> str | int | float | bool:
    """Нормализует значение перед bind в structlog contextvars."""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def bind_log_context(*, reset: bool = False, **context: Any) -> None:
    """Привязывает бизнес-контекст к текущей цепочке логов.

    Args:
        reset: Сбрасывает управляемые ключи перед bind, не трогая trace context.
        **context: Значения, которые нужно привязать к текущему request/message scope.
    """
    if reset:
        unbind_contextvars(*MANAGED_LOG_CONTEXT_KEYS)

    normalized_context = {
        key: _normalize_log_context_value(value)
        for key, value in context.items()
        if key in MANAGED_LOG_CONTEXT_KEYS and value is not None
    }
    if normalized_context:
        bind_contextvars(**normalized_context)


def bind_broker_log_context(message: Any, *, reset: bool = True) -> None:
    """Извлекает ключевой контекст из broker-сообщения и добавляет его в логи."""
    header = getattr(message, "header", None)
    payload = getattr(message, "payload", None)
    context: dict[str, Any] = {}

    for source in (message, header, payload):
        if source is None:
            continue
        for key in MANAGED_LOG_CONTEXT_KEYS:
            value = getattr(source, key, None)
            if value is not None and key not in context:
                context[key] = value

    bind_log_context(reset=reset, **context)
