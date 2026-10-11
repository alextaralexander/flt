"""Тесты базовых схем Kafka-сообщений, которые наследуют сгенерированные схемы модулей."""

from datetime import UTC

import pytest

from app.core.kafka.base_message import BaseMessageHeaderSchema, BaseMessageSchema


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-04-R20")]


class TestBaseMessage:
    """Заголовок получает идентификаторы и время создания по умолчанию (Arrange / Act / Assert)."""

    def test_header_defaults_are_unique_and_utc(self) -> None:
        """У каждого заголовка свои `message_id`/`correlation_id`, время — tz-aware UTC."""
        # - Act -
        first = BaseMessageHeaderSchema(message_type="sample")
        second = BaseMessageHeaderSchema(message_type="sample")

        # - Assert -
        assert first.message_id != second.message_id
        assert first.correlation_id != second.correlation_id
        assert first.creation_time.tzinfo is UTC

    def test_message_roundtrip(self) -> None:
        """Сообщение сериализуется в JSON и читается обратно без потерь."""
        # - Arrange -
        message = BaseMessageSchema(header=BaseMessageHeaderSchema(message_type="sample"), payload={"foo": "bar"})

        # - Act -
        restored = BaseMessageSchema.model_validate_json(message.model_dump_json())

        # - Assert -
        assert restored == message
