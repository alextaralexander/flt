"""OpenTelemetry-трассировка.

Модуль экспортирует прокси-`tracer`, который можно безопасно импортировать
при создании брокеров/роутеров: реальный provider настраивается позже,
в `lifespan` приложения (`setup_telemetry`), и прокси начинает делегировать
ему автоматически. До настройки спаны — no-op.
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


SERVICE_NAME = "python_boilerplate"

# ProxyTracer: резолвится в реальный tracer после setup_telemetry().
tracer = trace.get_tracer(SERVICE_NAME)


def setup_telemetry(service_name: str, endpoint: str) -> TracerProvider:
    """Настраивает OpenTelemetry tracer provider (вызывается на старте приложения).

    Без OTLP-endpoint-а трассировка работает in-process (экспортер не подключается).
    """
    tracer_provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
    )

    if endpoint:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)),
        )

    trace.set_tracer_provider(tracer_provider)
    return tracer_provider


def stop_telemetry(tracer_provider: TracerProvider) -> None:
    """Завершает OpenTelemetry tracer provider (flush + shutdown экспортеров)."""
    tracer_provider.shutdown()
