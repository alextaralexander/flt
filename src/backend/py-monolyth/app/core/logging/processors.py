"""Structlog-процессоры: нормализация, обязательные поля и маскирование записей (ADR-010, раздел 3.2).

- `add_module` — поле `module` (второй сегмент логгера `flt.<module>.*`, иначе `core`);
- `add_process_context` — `instance_id`, `role`, `stand` процесса;
- `redact_sensitive_keys` — маскирование ключей из списка и значений, похожих на JWT и ключи
  провайдеров, на любой глубине (SYS-02-R46, SYS-08-R18); применяется последним шагом цепочки.
"""

import re
from collections.abc import Mapping
from typing import Any

import structlog
from opentelemetry import trace
from structlog.types import EventDict

from configs.settings import settings
from configs.stands import instance_id


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


CORE_MODULE = "core"
MODULE_LOGGER_PREFIX = "flt."


def add_module(_: structlog.types.WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Добавляет `module`: второй сегмент имени логгера `flt.<module>.*`; прочие логгеры — `core` (ADR-010)."""
    logger_name = str(event_dict.get("logger") or "")
    module = CORE_MODULE
    if logger_name.startswith(MODULE_LOGGER_PREFIX):
        module = logger_name.split(".")[1] or CORE_MODULE
    event_dict.setdefault("module", module)
    return event_dict


def add_process_context(_: structlog.types.WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Добавляет `instance_id` (`HOSTNAME`), `role` (`APP_ROLE`) и `stand` (`STAND_NAME`) — неизменны в процессе."""
    event_dict.setdefault("instance_id", instance_id())
    event_dict.setdefault("role", settings.role.value)
    event_dict.setdefault("stand", settings.STAND_NAME)
    return event_dict


MASK = "***"
# ADR-010, раздел 3.2 п. 3 и SYS-08-R18; сравнение — без учёта регистра, `-` равен `_`.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "api_key",
        "secret",
        "email",
        "phone",
        "prompt",
        "completion",
        "content",
        "x_api_key",
        "api_key_ciphertext",
        "extra_headers",
    }
)
# Ключи вида `<что-то>_<суффикс>` (`client_secret`, `x_csrf_token`, `user_password`) — тоже секреты.
SENSITIVE_SUFFIXES = ("_password", "_token", "_secret", "_api_key")
SENSITIVE_VALUE_RE = re.compile(
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"  # JWT
    r"|sk-[A-Za-z0-9_-]{16,}"  # OpenAI-совместимые ключи
    r"|AQVN[A-Za-z0-9_-]{20,}"  # Yandex Cloud API-ключ
    r"|y0_[A-Za-z0-9_-]{20,}"  # Yandex OAuth-токен
    r"|flta_[A-Za-z0-9_-]{20,}"  # токен локального агента (ADR-008)
)


def _is_sensitive_key(key: object) -> bool:
    """Ключ из списка маскирования или с секретным суффиксом."""
    normalized = str(key).lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or normalized.endswith(SENSITIVE_SUFFIXES)


def _redact(value: Any) -> Any:
    """Копия значения с замаскированными ключами и секретными подстроками (исходный объект не меняется)."""
    if isinstance(value, str):
        return SENSITIVE_VALUE_RE.sub(MASK, value)
    if isinstance(value, Mapping):
        return {key: MASK if _is_sensitive_key(key) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_sensitive_keys(_: structlog.types.WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Маскирует секреты и ПД в записи: ключи из списка → `***`, JWT и ключи провайдеров в строках → `***`."""
    for key in list(event_dict):
        event_dict[key] = MASK if _is_sensitive_key(key) else _redact(event_dict[key])
    return event_dict
