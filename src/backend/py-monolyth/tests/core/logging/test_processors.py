"""Тесты процессоров логов: поле `module`, контекст процесса, маскирование секретов и ПД.

ADR-010, раздел 3.2 (обязательные поля, `redact_sensitive_keys`); SYS-02-R46; SYS-08-R18.
"""

from typing import Any

import pytest

from app.core.logging.config import LoggerConfig
from app.core.logging.processors import (
    MASK,
    SENSITIVE_KEYS,
    add_module,
    add_process_context,
    redact_sensitive_keys,
)
from configs.settings import settings
from configs.stands import instance_id


pytestmark = pytest.mark.no_db

JWT = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlX3ZhbHVl"  # pragma: allowlist secret
PROVIDER_KEYS = [
    "sk-abcdefghijklmnopqrstuvwx",  # pragma: allowlist secret
    "AQVN1234567890abcdefghijklmnopqrstuv",  # pragma: allowlist secret
    "y0_AgAAAAAAbcdefghijklmnopqrstuvwx",
    "flta_abcdefghijklmnopqrstuvwxyz012345",  # pragma: allowlist secret
]


def _run(processor: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Применяет процессор structlog к записи."""
    result: dict[str, Any] = processor(None, "info", event)
    return result


@pytest.mark.req("SYS-02-R46")
class TestAddModule:
    """`module` — второй сегмент имени логгера `flt.<module>.*`, иначе `core`."""

    @pytest.mark.parametrize(
        ("logger", "module"),
        [
            ("flt.identity.services.registration", "identity"),
            ("flt.core.security", "core"),
            ("flt.llm_gateway", "llm_gateway"),
            ("app", "core"),
            ("uvicorn.error", "core"),
            ("kafka", "core"),
            (None, "core"),
        ],
    )
    def test_module_from_logger_name(self, logger: str | None, module: str) -> None:
        """Логгеры модулей дают имя модуля, остальные — `core`."""
        event = {"event": "x"} if logger is None else {"event": "x", "logger": logger}
        assert _run(add_module, event)["module"] == module

    def test_explicit_module_is_kept(self) -> None:
        """Явно переданный `module` не перезаписывается."""
        assert _run(add_module, {"logger": "flt.identity.x", "module": "custom"})["module"] == "custom"


@pytest.mark.req("SYS-02-R46")
def test_process_context_fields() -> None:
    """`instance_id`, `role`, `stand` — в каждой записи (ADR-010, раздел 3.2)."""
    event = _run(add_process_context, {"event": "x"})
    assert event["instance_id"] == instance_id()
    assert event["role"] == settings.role.value
    assert event["stand"] == settings.STAND_NAME


@pytest.mark.req("SYS-02-R46")
class TestRedactSensitiveKeys:
    """Ключи из списка и значения, похожие на токены и ключи провайдеров, маскируются на любой глубине."""

    @pytest.mark.parametrize("key", sorted(SENSITIVE_KEYS))
    def test_each_listed_key_is_masked(self, key: str) -> None:
        """Каждый ключ списка ADR-010 и SYS-08-R18 маскируется, в том числе во вложенных структурах."""
        # - Act -
        event = _run(
            redact_sensitive_keys,
            {"event": "x", key: "value", "nested": {key.upper(): "value"}, "items": [{key: "value"}]},
        )

        # - Assert -
        assert event[key] == MASK
        assert event["nested"][key.upper()] == MASK
        assert event["items"][0][key] == MASK

    @pytest.mark.parametrize("key", ["client_secret", "x_csrf_token", "jwt_token", "user_password", "X-Api-Key"])
    def test_suffix_variants_are_masked(self, key: str) -> None:
        """Варианты с префиксом (`client_secret`, `x_csrf_token`) и через дефис тоже маскируются."""
        assert _run(redact_sensitive_keys, {key: "value"})[key] == MASK

    @pytest.mark.parametrize("secret", [JWT, *PROVIDER_KEYS])
    def test_secret_values_in_strings_are_masked(self, secret: str) -> None:
        """JWT и ключи провайдеров в произвольных строках (в том числе в тексте сообщения) маскируются."""
        # - Act -
        event = _run(redact_sensitive_keys, {"event": f"failed with {secret} here", "detail": [f"Bearer {secret}"]})

        # - Assert -
        assert secret not in str(event)
        assert event["event"] == f"failed with {MASK} here"

    def test_safe_fields_are_untouched(self) -> None:
        """UUID пользователя, IP, числа и обычный текст не изменяются."""
        event = {
            "event": "200 POST /api/v1/auth/login",
            "user_id": "8f1c4e2a-0d7b-4c3e-9a1f-5e6d7c8b9a01",
            "network": {"client": {"ip": "203.0.113.7"}},
            "duration": 0.04,
            "token_count": 12,
        }
        assert _run(redact_sensitive_keys, dict(event)) == event


@pytest.mark.req("SYS-02-R46")
def test_pipeline_redacts_last_and_has_required_fields() -> None:
    """Цепочка процессоров JSON-логов: обязательные поля добавлены, маскирование — последним шагом."""
    # - Arrange -
    pipeline = LoggerConfig().pipeline(json_format=True)
    event: dict[str, Any] = {"event": f"token {JWT}", "logger": "flt.identity.api", "password": "p"}

    # - Act -
    for processor in pipeline:
        if processor in (add_module, add_process_context, redact_sensitive_keys):
            event = _run(processor, event)

    # - Assert -
    assert pipeline[-1] is redact_sensitive_keys
    assert add_module in pipeline and add_process_context in pipeline
    assert event["module"] == "identity"
    assert event["password"] == MASK
    assert JWT not in event["event"]
