"""Отправка логов в OpenSearch батчами.

Клиент создаётся только при включённом `OPEN_SEARCH_LOGS_ENABLED` — из
`configure_opensearch_sink()`, который вызывает `LoggerConfig.setup_logging`.
Импорт модуля побочных эффектов не имеет.
"""

import atexit
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

import structlog
import urllib3
from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk
from structlog.tracebacks import ExceptionDictTransformer
from structlog.types import EventDict

from configs.settings import settings


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BATCH_SIZE: int = 50
BATCH_INTERVAL_SECONDS: int = 5

EXCLUDED_OPENSEARCH_LOGGERS = (
    "opensearch",
    "urllib3",
    "urllib3.connectionpool",
)

OPENSEARCH_EXCEPTION_DICT_RENDERER = structlog.processors.ExceptionRenderer(
    ExceptionDictTransformer(
        show_locals=True,
        # None = без усечения repr-ов локальных переменных (аннотация structlog — int).
        locals_max_length=None,  # type: ignore[arg-type]
        locals_max_string=None,  # type: ignore[arg-type]
    ),
)
OPENSEARCH_EXCEPTION_TEXT_RENDERER = structlog.processors.ExceptionRenderer()

_client: OpenSearch | None = None
_batch_buffer: list[Any] = []
_batch_lock = threading.Lock()
_batch_sender_start_lock = threading.Lock()
_batch_sender_started = threading.Event()
# Сигнал фоновому sender-у «буфер полон, отправляй сейчас» — сетевой вызов
# выполняет только фоновый поток, никогда поток, из которого пишется лог.
_flush_requested = threading.Event()


def configure_opensearch_sink() -> bool:
    """Создаёт клиент и запускает background-sender; False, если sink выключен."""
    global _client
    if not settings.OPEN_SEARCH_LOGS_ENABLED:
        return False

    if _client is None:
        _client = OpenSearch(
            [settings.OPEN_SEARCH_URL],
            http_auth=(settings.OPEN_SEARCH_USER_NAME, settings.OPEN_SEARCH_PASSWORD),
            verify_certs=settings.OPEN_SEARCH_VERIFY_SSL,
            max_retries=3,
            retry_on_timeout=True,
            timeout=30,
            maxsize=25,  # Максимальное количество соединений в пуле
            pool_maxsize=25,  # Количество пулов
        )
    _start_batch_sender()
    return True


def sanitize_log_data(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Очищает event_dict от несериализуемых объектов рекурсивно."""
    return cast("dict[str, Any]", _recursive_sanitize(event_dict))


def _recursive_sanitize(data: Any) -> Any:
    """Рекурсивно очищает данные от несериализуемых объектов."""
    # Пропускаем служебные поля structlog
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key.startswith("_"):
                continue
            result[key] = _recursive_sanitize(value)
        return result

    # Обрабатываем списки
    elif isinstance(data, list):
        return [_recursive_sanitize(item) for item in data]

    # Базовые типы - оставляем как есть
    elif isinstance(data, (str, int, float, bool, type(None))):
        return data

    # datetime -> строка
    elif isinstance(data, datetime):
        return data.isoformat()

    # UUID -> строка
    elif isinstance(data, UUID):
        return str(data)

    # Enum -> значение
    elif isinstance(data, Enum):
        return data.value

    # Для объектов с __dict__ рекурсивно обрабатываем атрибуты
    elif hasattr(data, "__dict__"):
        return _recursive_sanitize(data.__dict__)

    # Все остальное -> строковое представление
    else:
        try:
            return str(data)
        except Exception:
            return f"<unserializable: {type(data).__name__}>"


def compact_opensearch_log_record(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Оставляет в OpenSearch только стабильные top-level поля.

    Вложенные payload-поля вроде `data`, `extra`, `network` приводят к росту
    количества полей в индексе из-за dynamic mapping. Для поиска по логам нам
    достаточно фиксированного набора скалярных атрибутов.
    """
    compact_record: dict[str, Any] = {}
    for key, value in event_dict.items():
        if isinstance(value, (dict, list)):
            continue
        compact_record[key] = value
    return compact_record


def normalize_opensearch_timestamp(value: Any) -> str:
    """Приводит timestamp к формату, который принимает OpenSearch date mapping."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    if isinstance(value, str):
        if "T" in value:
            try:
                parsed_timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
            if parsed_timestamp.tzinfo is None:
                parsed_timestamp = parsed_timestamp.replace(tzinfo=UTC)
            return parsed_timestamp.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed_timestamp = datetime.strptime(value, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
            return parsed_timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z")

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_exception_with_locals(exception_text: Any, exception_stacks: Any) -> str:
    """Форматирует traceback с locals в человекочитаемую многострочную строку."""
    lines: list[str] = []
    if exception_text:
        lines.append(str(exception_text).rstrip())

    if not isinstance(exception_stacks, list):
        return "\n".join(lines)

    locals_lines: list[str] = []
    for stack in exception_stacks:
        if not isinstance(stack, dict):
            continue

        exc_type = stack.get("exc_type")
        exc_value = stack.get("exc_value")
        if exc_type or exc_value:
            locals_lines.append(f"{exc_type or 'Exception'}: {exc_value or ''}".rstrip())

        for frame in stack.get("frames") or []:
            if not isinstance(frame, dict):
                continue

            filename = frame.get("filename", "<unknown>")
            lineno = frame.get("lineno", "?")
            function_name = frame.get("name", "<module>")
            locals_lines.append(f'  File "{filename}", line {lineno}, in {function_name}')

            frame_locals = frame.get("locals")
            if not isinstance(frame_locals, dict) or not frame_locals:
                continue

            locals_lines.append("    locals:")
            for key, value in frame_locals.items():
                locals_lines.append(f"      {key} = {value}")

    if locals_lines:
        if lines:
            lines.append("")
        lines.append("Locals by frame:")
        lines.extend(locals_lines)

    return "\n".join(lines)


def add_opensearch_exception_fields(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Добавляет в запись OpenSearch полный traceback с locals из `exc_info`."""
    exc_info = event_dict.pop("exc_info", None)
    if not exc_info:
        return event_dict

    exception_text_event = {"exc_info": exc_info}
    OPENSEARCH_EXCEPTION_TEXT_RENDERER(None, "", exception_text_event)
    exception_text = exception_text_event.get("exception")

    exception_dict_event = {"exc_info": exc_info}
    OPENSEARCH_EXCEPTION_DICT_RENDERER(None, "", exception_dict_event)
    exception_stacks = exception_dict_event.get("exception")
    if exception_text is None and exception_stacks is None:
        return event_dict

    event_dict["exception_traceback_full"] = format_exception_with_locals(exception_text, exception_stacks)

    if isinstance(exception_stacks, list) and exception_stacks:
        last_exception = exception_stacks[-1]
        if isinstance(last_exception, dict):
            event_dict["exception_type"] = last_exception.get("exc_type")
            event_dict["exception_message"] = last_exception.get("exc_value")

    return event_dict


def prepare_opensearch_log_record(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Готовит отдельную копию записи для отправки в OpenSearch."""
    opensearch_event_dict = dict(event_dict)
    add_opensearch_exception_fields(opensearch_event_dict)

    clean_data = sanitize_log_data(opensearch_event_dict)
    clean_data["service_name"] = settings.open_search_service_name
    clean_data["timestamp"] = normalize_opensearch_timestamp(clean_data.get("timestamp"))

    return clean_data


def _format_for_bulk(log_records: list[Any]) -> Iterator[dict[str, Any]]:
    """Форматирует записи для bulk-запроса OpenSearch."""
    for log_record in log_records:
        yield {
            "_index": settings.open_search_index,
            "_source": log_record,
        }


def _send_batch_to_opensearch(log_records: list[Any]) -> None:
    """Отправляет подготовленный батч в OpenSearch."""
    if not log_records or _client is None:
        return

    try:
        bulk(_client, _format_for_bulk(log_records), refresh=False)
    except Exception as exc:
        print(f"Failed to send batch logs to OpenSearch: {exc}", file=sys.stderr)


def flush_batch_buffer() -> None:
    """Сбрасывает накопленный буфер логов в OpenSearch."""
    with _batch_lock:
        if not _batch_buffer:
            return
        to_send = _batch_buffer[:]
        _batch_buffer.clear()

    _send_batch_to_opensearch(to_send)


def _batch_sender() -> None:
    """Фоновый цикл: сбрасывает буфер раз в BATCH_INTERVAL_SECONDS или по сигналу «буфер полон»."""
    while True:
        _flush_requested.wait(timeout=BATCH_INTERVAL_SECONDS)
        _flush_requested.clear()
        flush_batch_buffer()


def _start_batch_sender() -> None:
    """Запускает background sender для OpenSearch один раз на процесс."""
    if _batch_sender_started.is_set():
        return

    with _batch_sender_start_lock:
        if _batch_sender_started.is_set():
            return

        threading.Thread(target=_batch_sender, daemon=True, name="opensearch-batch-sender").start()
        atexit.register(flush_batch_buffer)
        _batch_sender_started.set()


def send_to_opensearch_batch(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Structlog-процессор: кладёт запись в batch-буфер, отправляет фоновый sender.

    Процессор выполняется в потоке, из которого пишется лог (в т.ч. в event loop),
    поэтому здесь только CPU-подготовка записи и буферизация: при заполнении
    буфера сетевую отправку делает фоновый поток по сигналу `_flush_requested`.
    """
    if _client is None:
        return event_dict

    logger_name = event_dict.get("logger", "")
    if logger_name in EXCLUDED_OPENSEARCH_LOGGERS:
        return event_dict
    try:
        clean_data = prepare_opensearch_log_record(dict(event_dict))

        with _batch_lock:
            _batch_buffer.append(clean_data)
            buffer_is_full = len(_batch_buffer) >= BATCH_SIZE
        if buffer_is_full:
            _flush_requested.set()
    except Exception as exc:
        print(f"Error preparing log for OpenSearch: {exc}", file=sys.stderr)

    return event_dict
