"""HTTP-middleware сбора Prometheus-метрик (количество и латентность запросов).

Метка `endpoint` — шаблон маршрута (`/api/v1/<module>/<resources>/{obj_id}`), а не сырой путь:
сырые пути с UUID/ID дают неограниченный рост числа серий (cardinality explosion).
Несматченные пути (404 от сканеров и опечаток) схлопываются в одну серию `unmatched`.
"""

import time

from prometheus_client import Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send


REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

# Единая серия для запросов, не сматченных ни одним маршрутом.
UNMATCHED_ENDPOINT = "unmatched"


class PrometheusMiddleware:
    """Pure-ASGI middleware: замеряет запрос и инкрементит счётчики по методу/маршруту/статусу.

    Реализован без `BaseHTTPMiddleware`: тот оборачивает ответ в свой поток
    и ломает streaming-ответы, добавляя накладные расходы на каждый запрос.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Принимает следующий ASGI-app в цепочке middleware."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Пропускает не-HTTP scope; для HTTP собирает метрики даже при исключении."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        # Если ответ не начался (исключение до response.start) — считаем 500:
        # его сформирует внешний logging-middleware.
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start_time
            # FastAPI кладёт сматченный маршрут в scope["route"] во время роутинга.
            # path_format — шаблон маршрута с префиксом его роутера (`/<resources>/{obj_id}`),
            # но без префиксов include_router (`/v1`): для метрик важна ограниченность
            # набора значений, а не дословный внешний путь.
            route = scope.get("route")
            endpoint = getattr(route, "path_format", None) or UNMATCHED_ENDPOINT
            method = scope["method"]
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)
