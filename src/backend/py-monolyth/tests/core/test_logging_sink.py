"""Unit-тесты чистых функций подготовки логов для OpenSearch."""

import enum
import threading
import uuid
from datetime import UTC, datetime

import pytest

from app.core.logging import opensearch_sink
from app.core.logging.opensearch_sink import (
    compact_opensearch_log_record,
    normalize_opensearch_timestamp,
    sanitize_log_data,
)


pytestmark = pytest.mark.no_db


class _Color(enum.Enum):
    RED = "red"


class TestSanitizeLogData:
    """`sanitize_log_data` приводит запись к JSON-сериализуемому виду."""

    def test_converts_non_serializable_values(self) -> None:
        """UUID/datetime/Enum приводятся к строкам и значениям."""
        # - Arrange -
        record_id = uuid.uuid4()
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        event = {"id": record_id, "when": moment, "color": _Color.RED, "count": 3}

        # - Act -
        clean = sanitize_log_data(event)

        # - Assert -
        assert clean == {"id": str(record_id), "when": moment.isoformat(), "color": "red", "count": 3}

    def test_drops_private_keys_and_recurses(self) -> None:
        """Ключи с подчёркиванием отбрасываются, вложенность обходится рекурсивно."""
        # - Arrange -
        event = {"_private": "skip", "nested": {"_hidden": 1, "kept": [1, "two"]}}

        # - Act -
        clean = sanitize_log_data(event)

        # - Assert -
        assert clean == {"nested": {"kept": [1, "two"]}}


class TestNormalizeTimestamp:
    """`normalize_opensearch_timestamp` приводит время к формату date mapping."""

    def test_datetime_is_rendered_as_utc_z(self) -> None:
        """Значение datetime сериализуется в ISO-строку с суффиксом Z."""
        # - Arrange -
        moment = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)

        # - Act / Assert -
        assert normalize_opensearch_timestamp(moment) == "2026-01-02T03:04:05.123456Z"

    def test_naive_string_gets_utc_timezone(self) -> None:
        """Строка формата логгера получает таймзону UTC."""
        # - Act / Assert -
        assert normalize_opensearch_timestamp("2026-01-02 03:04:05.123456") == "2026-01-02T03:04:05.123456Z"

    def test_garbage_falls_back_to_now(self) -> None:
        """Непарсируемое значение заменяется текущим временем (валидным для mapping)."""
        # - Act -
        normalized = normalize_opensearch_timestamp(object())

        # - Assert -
        assert normalized.endswith("Z")


class TestCompactRecord:
    """`compact_opensearch_log_record` оставляет только скалярные поля."""

    def test_nested_structures_are_dropped(self) -> None:
        """dict/list-поля не попадают в индекс (защита от взрыва dynamic mapping)."""
        # - Arrange -
        event = {"event": "ok", "duration": 1.5, "network": {"ip": "127.0.0.1"}, "tags": ["a"]}

        # - Act -
        compact = compact_opensearch_log_record(event)

        # - Assert -
        assert compact == {"event": "ok", "duration": 1.5}


class TestSendToOpensearchBatch:
    """Процессор только буферизует запись: сетевую отправку делает фоновый sender."""

    def test_full_buffer_wakes_sender_without_inline_send(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """При заполнении буфера процессор не отправляет батч сам, а сигналит фоновому потоку.

        Проверки:
        - Из потока логгера сетевой вызов не выполняется (event loop не блокируется).
        - Выставлен сигнал `_flush_requested` для фонового sender-а.
        - Все записи остались в буфере до фоновой отправки.
        """
        # - Arrange -
        sent_batches: list[list[object]] = []
        monkeypatch.setattr(opensearch_sink, "_client", object())
        monkeypatch.setattr(opensearch_sink, "_batch_buffer", [])
        monkeypatch.setattr(opensearch_sink, "_flush_requested", threading.Event())
        monkeypatch.setattr(opensearch_sink, "_send_batch_to_opensearch", sent_batches.append)

        # - Act -
        for index in range(opensearch_sink.BATCH_SIZE):
            opensearch_sink.send_to_opensearch_batch(None, "info", {"event": f"msg-{index}"})

        # - Assert -
        assert not sent_batches
        assert opensearch_sink._flush_requested.is_set()
        assert len(opensearch_sink._batch_buffer) == opensearch_sink.BATCH_SIZE
