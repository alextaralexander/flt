"""Structlog-процессоры: нормализация и фильтрация полей записей."""

from typing import Any

import structlog
from opentelemetry import trace
from structlog.types import EventDict


EXCLUDED_CONTEXT_KEYS = {
    "traceparent",
    "root_traceparent",
}
KAFKA_PROCESSED_MESSAGE_EXCLUDED_KEYS = {
    "duration",
}


def drop_contextvars_keys(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Удаляет служебные trace-ключи из contextvars."""
    for key in EXCLUDED_CONTEXT_KEYS:
        event_dict.pop(key, None)
    return event_dict


def add_open_telemetry_trace_context(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Добавляет `trace_id`/`span_id` активного OTel-span в запись лога.

    Унифицирует корреляцию логов и трейсов для всех путей: на Kafka их уже
    кладёт брокерный OTel-middleware (`get_trace_data` → contextvars), а на REST
    span создаёт `FastAPIInstrumentor`, но в contextvars ничего не пишет. Значения
    из contextvars имеют приоритет (`setdefault`), запись без активного span-а не
    трогается.
    """
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context.is_valid:
        return event_dict

    event_dict.setdefault("trace_id", format(span_context.trace_id, "032x"))
    event_dict.setdefault("span_id", format(span_context.span_id, "016x"))
    return event_dict


def drop_kafka_processed_message_noise(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Убирает шумные служебные поля из итогового Kafka-лога обработки.

    Для `Processed message.` correlation_id подтягивается из contextvars уже после
    выполнения handler'а, а duration добавляется middleware. Эти поля зашумляют
    инфраструктурный лог и не несут отдельной пользы в финальной записи.
    """
    logger_name = str(event_dict.get("logger", "")).strip()
    if logger_name != "kafka" or event_dict.get("event") != "Processed message.":
        return event_dict

    for key in KAFKA_PROCESSED_MESSAGE_EXCLUDED_KEYS:
        event_dict.pop(key, None)

    return event_dict


def flatten_structlog_extra(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Переносит значения из `extra` в top-level поля structlog.

    FastStream вызывает structlog как `logger.log(..., extra={...})`. Для
    structlog это обычный keyword-аргумент, поэтому без нормализации поля
    оказываются вложенными в `extra`.
    """
    extra = event_dict.pop("extra", None)
    if not isinstance(extra, dict):
        if extra is not None:
            event_dict["extra"] = extra
        return event_dict

    for key, value in extra.items():
        event_dict.setdefault(str(key), value)

    return event_dict


def move_logger_to_event_prefix(
    _: structlog.types.WrappedLogger,
    __: str,
    event_dict: EventDict,
) -> EventDict:
    """Переносит имя логгера в начало event для консольного вывода."""
    logger_name = event_dict.pop("logger", None)
    event = event_dict.get("event")

    if logger_name and event:
        event_dict["event"] = f"[{logger_name}] {event}"
    elif logger_name:
        event_dict["event"] = f"[{logger_name}]"

    return event_dict


def rename_event_key(_: structlog.types.WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Переименовывает ключ 'event' в 'message' для совместимости с Datadog.

    Записи логов хранят текстовые сообщения в поле `event`, но Datadog
    использует поле `message`. Этот процессор перемещает значение из одного поля в другое.
    См. https://github.com/hynek/structlog/issues/35#issuecomment-591321744
    """
    event_dict["message"] = event_dict.pop("event")
    return event_dict


def drop_color_message_key(_: structlog.types.WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Удаляет ключ 'color_message', если он присутствует.

    Uvicorn дублирует сообщение лога в поле `color_message`. Этот процессор
    удаляет ключ из словаря событий, если он присутствует.
    """
    event_dict.pop("color_message", None)
    return event_dict
