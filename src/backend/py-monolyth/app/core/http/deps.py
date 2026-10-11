"""FastAPI-зависимости HTTP-слоя shared kernel для контроллеров модулей.

- `Idempotent()` — идемпотентность `POST` по `Idempotency-Key` (SYS-03-R18);
- `RequestContextDep` — контекст запроса (SYS-03-R20, R30);
- `RequestLanguage` — язык запроса (SYS-07-R3);
- `PageLimit`, `PageCursor`, `PageOffset` — параметры пагинации (SYS-03-R12, R13).
"""

from app.core.http.context import RequestContext, RequestContextDep, get_request_context
from app.core.http.idempotency import Idempotent
from app.core.http.pagination import PageCursor, PageLimit, PageOffset
from app.core.i18n.request_language import RequestLanguage


__all__ = [
    "Idempotent",
    "PageCursor",
    "PageLimit",
    "PageOffset",
    "RequestContext",
    "RequestContextDep",
    "RequestLanguage",
    "get_request_context",
]
