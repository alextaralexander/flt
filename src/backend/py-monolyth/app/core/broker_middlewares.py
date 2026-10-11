"""Совместимые с FastStream 0.6 OpenTelemetry-middleware для брокеров.

`py_main_lib` (её OTel-middleware) написана под FastStream **0.5**, где
`BaseMiddleware` имел сигнатуру `__init__(self, msg=None)`, а `publish_scope`
получал `(msg, *args, **kwargs)`. В FastStream **0.6** контракт изменился:

- `BaseMiddleware.__init__(self, msg, /, *, context)` — `context` обязателен;
- per-message инстанс создаётся вызовом `mw(msg, context=...)`;
- `consume_scope(self, call_next, msg)` получает `StreamMessage`;
- `publish_scope(self, call_next, cmd)` получает единый `PublishCommand`.

Boilerplate закреплён на `faststream>=0.6.7` (см. `pyproject.toml`), поэтому
прямой вызов `KafkaOpenTelemetryMiddleware(tracer=...)` из `py_main_lib`
падает на этапе импорта роутера. Менять `py_main_lib` и версии пакетов
нельзя, поэтому слой совместимости живёт здесь: адаптер **наследует** классы
`py_main_lib` и переиспользует их трейс-семантику (W3C `traceparent` +
кастомный `root_traceparent`, привязка к structlog-contextvars через
`get_trace_data`), переопределяя только те четыре метода, чьи сигнатуры
изменились в 0.6. Так провод к трассировке идентичен остальным сервисам SOA
(на 0.5 + `py_main_lib`) — трейс продолжается и подхватывается между сервисами.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from faststream import BaseMiddleware
from opentelemetry import propagate, trace
from opentelemetry.trace import Status, StatusCode, Tracer
from structlog.contextvars import bind_contextvars, clear_contextvars


if TYPE_CHECKING:
    # Для типизации миксин «наследует» базовый OTel-middleware `py_main_lib`
    # (там объявлены `get_traceparents`/`get_trace_data` и цепочка до `BaseMiddleware`).
    # В рантайме миксин остаётся чистым — реальную базу даёт MRO конкретного класса.
    from py_main_lib.middlewares.base_opentelemetry_middleware import (
        BaseOpenTelemetryMiddleware as _AdapterTypingBase,
    )
else:
    _AdapterTypingBase = object


class NoopOpenTelemetryMiddleware(BaseMiddleware):
    """Прозрачный middleware для окружений, где OTel-интеграция недоступна."""

    def __init__(self, msg: Any | None = None, *, context: Any = None, **_: Any) -> None:
        """Инициализирует middleware для конкретного сообщения."""
        super().__init__(msg, context=context)

    def __call__(self, msg: Any = None, /, *, context: Any = None) -> BaseMiddleware:
        """Фабрика per-message инстанса (конвенция FastStream 0.6)."""
        return type(self)(msg, context=context)

    async def consume_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        message: Any,
    ) -> Any:
        """Передаёт сообщение дальше без изменений."""
        return await call_next(message)


class _FastStream06TelemetryAdapter(_AdapterTypingBase):
    """Переносит OTel-middleware `py_main_lib` (FastStream 0.5) на API 0.6.

    Миксин ставится ПЕРЕД классом `py_main_lib` в MRO и переопределяет только
    методы с изменившейся в 0.6 сигнатурой. Хелперы (`get_traceparents`,
    `get_trace_data`, `get_message_type`) наследуются от `py_main_lib` без
    изменений — трейс-контракт остаётся тем же, что у остальных сервисов FLT.
    """

    tracer: Tracer

    def __init__(self, tracer: Tracer, msg: Any | None = None, *, context: Any = None) -> None:
        """Сохраняет tracer и инициализирует базовый middleware по контракту 0.6."""
        self.tracer = tracer
        BaseMiddleware.__init__(self, msg, context=context)

    def __call__(self, msg: Any = None, /, *, context: Any = None) -> Any:
        """Фабрика per-message инстанса (конвенция FastStream 0.6)."""
        return type(self)(self.tracer, msg, context=context)

    async def consume_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        msg: Any,
    ) -> Any:
        """Открывает span на приём сообщения, продолжая трейс из заголовков.

        Если во входящих заголовках есть `traceparent` — span становится
        продолжением трейса вышестоящего сервиса; иначе создаётся новый корень.
        Трейс-контекст привязывается к structlog-contextvars (`get_trace_data`)
        для корреляции логов и спанов.
        """
        headers = dict(getattr(msg, "headers", None) or {})
        clear_contextvars()
        traceparent, root_traceparent = self.get_traceparents(headers)
        root_ctx = propagate.extract({"traceparent": traceparent}) if traceparent else None

        with self.tracer.start_as_current_span(self._consume_span_name(msg), context=root_ctx) as span:
            if root_ctx:
                bind_contextvars(root_traceparent=root_traceparent, traceparent=traceparent)
            else:
                carrier: dict[str, Any] = {}
                propagate.inject(carrier, context=trace.set_span_in_context(span))
                bind_contextvars(root_traceparent=carrier["traceparent"], traceparent=carrier["traceparent"])

            self.get_trace_data()
            try:
                result = await call_next(msg)
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            span.set_status(Status(StatusCode.OK))
            return result

    async def publish_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        cmd: Any,
    ) -> Any:
        """Открывает span на публикацию и прокидывает `traceparent` в заголовки.

        Внутри consume-скоупа span становится дочерним, и инъекция `traceparent`
        в `cmd.headers` связывает спаны нижестоящих сервисов в один трейс.
        """
        headers = dict(getattr(cmd, "headers", None) or {})
        traceparent, root_traceparent = self.get_traceparents(headers)
        current_ctx = trace.get_current_span().get_span_context()
        root_ctx = (
            propagate.extract({"traceparent": traceparent}) if (not current_ctx.is_valid and traceparent) else None
        )

        with self.tracer.start_as_current_span(self._publish_span_name(cmd), context=root_ctx):
            carrier: dict[str, Any] = {}
            propagate.inject(carrier)
            carrier["root_traceparent"] = root_traceparent or carrier["traceparent"]
            cmd.add_headers(carrier, override=True)
            self.get_trace_data()
            return await call_next(cmd)

    def _consume_span_name(self, msg: Any) -> str:
        """Имя span-а на приём: `message_type` из тела, иначе topic/subject."""
        try:
            body = json.loads(getattr(msg, "body", b"") or b"{}")
        except ValueError, TypeError:
            body = {}
        if isinstance(body, dict) and isinstance(body.get("header"), dict) and body["header"].get("message_type"):
            return str(body["header"]["message_type"])
        raw = getattr(msg, "raw_message", None)
        return str(getattr(raw, "topic", None) or getattr(raw, "subject", None) or "consume")

    @staticmethod
    def _publish_span_name(cmd: Any) -> str:
        """Имя span-а на публикацию — destination (topic/subject) команды."""
        return str(getattr(cmd, "destination", None) or "publish")


try:
    from py_main_lib.brokers.kafka.middlewares.opentelemetry_middleware import (
        KafkaOpenTelemetryMiddleware as _PyMainKafkaOTel,
    )

    class KafkaOpenTelemetryMiddleware(_FastStream06TelemetryAdapter, _PyMainKafkaOTel):  # type: ignore[misc,valid-type,unused-ignore]
        """Kafka OTel-middleware `py_main_lib`, адаптированный под FastStream 0.6."""

except ImportError:
    # py_main_lib слишком старая (нет `brokers.kafka`) — трассировка брокеров off.
    KafkaOpenTelemetryMiddleware = NoopOpenTelemetryMiddleware  # type: ignore[misc,assignment]


__all__ = (
    "KafkaOpenTelemetryMiddleware",
    "NoopOpenTelemetryMiddleware",
)
