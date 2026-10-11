"""Идемпотентность `POST` по заголовку `Idempotency-Key` (SYS-03-R18).

Состояние — только в Redis: ключ `shared_kernel:idempotency:<subject>:<key>`, где `<subject>` —
`user_id` аутентифицированного пользователя, иначе идентификатор анонимной сессии из cookie
`flt_anon_session` (OQ-77), иначе общий субъект `anonymous`.

Схема работы:
1. Зависимость `Idempotent()` атомарно (`SET NX`) создаёт запись «в работе» с отпечатком тела
   (`sha256` канонического JSON). Если запись уже есть: тот же отпечаток и готовый ответ — повтор
   сохранённого ответа с `Idempotent-Replayed: true`; тот же отпечаток в работе —
   `409 core.request_in_progress`; другой отпечаток — `422 core.idempotency_key_reused`.
2. `IdempotencyMiddleware` после ответа сохраняет статус, `Location`, `Content-Type` и тело на
   24 ч; ответ `5xx` или необработанное исключение снимают запись, чтобы повтор выполнился заново.

Запись «в работе» живёт `IN_PROGRESS_TTL` (таймаут REST в HAProxy — 60 с, ADR-012): если инстанс
остановится посреди запроса, ключ освободится сам. Без Redis запрос выполняется без гарантии
идемпотентности (fail-open, ADR-003): повтор выполнится заново.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Cookie, Header, Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.dao.caching import ModuleRedis, RedisUnavailableError
from app.core.http.errors import IdempotencyKeyReusedError, RequestInProgressError
from app.core.logging.context import app_logger


IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
ANON_SESSION_COOKIE = "flt_anon_session"
ANONYMOUS_SUBJECT = "anonymous"
RESPONSE_TTL = timedelta(hours=24)
IN_PROGRESS_TTL = timedelta(seconds=60)
_STATE_KEY = "flt_idempotency"
_STORED_HEADERS = ("location", "content-type")


class IdempotentReplayError(Exception):
    """Повтор запроса: обработчик исключений отдаёт сохранённый ответ вместо выполнения роута."""

    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        """Запоминает сохранённый ответ."""
        self.status = status
        self.headers = headers
        self.body = body
        super().__init__("Idempotent replay")

    def to_response(self) -> Response:
        """Сохранённый ответ с заголовком `Idempotent-Replayed: true`."""
        response = Response(content=self.body, status_code=self.status)
        response.headers.update(self.headers)
        response.headers[REPLAYED_HEADER] = "true"
        return response


@dataclass(frozen=True)
class IdempotencyClaim:
    """Запись «в работе», которую зависимость передаёт middleware через `scope["state"]`."""

    redis: ModuleRedis
    key: str
    fingerprint: str


def body_fingerprint(body: bytes) -> str:
    """`sha256` канонического JSON тела (сортировка ключей, без пробелов); не-JSON — по байтам."""
    try:
        canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    except ValueError, UnicodeDecodeError:
        canonical = body
    return hashlib.sha256(canonical).hexdigest()


def idempotency_subject(request: Request, anon_session: str | None) -> str:
    """Субъект ключа: `user_id` пользователя, иначе анонимная сессия, иначе `anonymous`."""
    user = getattr(request.state, "user", None)
    user_id = getattr(user, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    if anon_session:
        return f"anon:{anon_session}"
    return ANONYMOUS_SUBJECT


class Idempotent:
    """FastAPI-зависимость идемпотентности `POST`: `Depends(Idempotent())`.

    Объявляется в роуте после зависимости аутентификации, чтобы субъект был известен.

    Args:
        redis: `ModuleRedis("shared_kernel")`; в тестах — поверх отдельного клиента (имитация инстанса).
    """

    def __init__(self, redis: ModuleRedis | None = None) -> None:
        """Запоминает обёртку Redis (по умолчанию — общий клиент процесса)."""
        self._redis = redis or ModuleRedis("shared_kernel")

    async def __call__(
        self,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias=IDEMPOTENCY_HEADER)],
        anon_session: Annotated[str | None, Cookie(alias=ANON_SESSION_COOKIE, include_in_schema=False)] = None,
    ) -> UUID:
        """Захватывает ключ или повторяет сохранённый ответ.

        Returns:
            Значение `Idempotency-Key`.

        Raises:
            IdempotentReplayError: ответ на этот ключ уже сохранён (повтор).
            RequestInProgressError: первый запрос с этим ключом ещё выполняется.
            IdempotencyKeyReusedError: ключ уже использован с другим телом.
        """
        subject = idempotency_subject(request, anon_session)
        key = f"idempotency:{subject}:{idempotency_key}"
        fingerprint = body_fingerprint(await request.body())
        in_progress = json.dumps({"state": "in_progress", "fingerprint": fingerprint})
        try:
            for _ in range(2):
                if await self._redis.set(key, in_progress, ttl=IN_PROGRESS_TTL, nx=True):
                    request.scope.setdefault("state", {})[_STATE_KEY] = IdempotencyClaim(self._redis, key, fingerprint)
                    return idempotency_key
                stored = await self._redis.get_json(key)
                if stored is not None:
                    self._check_stored(stored, fingerprint)
            # Запись исчезла дважды между SET NX и GET — считаем запрос выполняющимся.
            raise RequestInProgressError()
        except RedisUnavailableError:
            app_logger.warning("core.idempotency_redis_unavailable")
            return idempotency_key

    @staticmethod
    def _check_stored(stored: dict[str, Any], fingerprint: str) -> None:
        """Решение по существующей записи: повтор, `409` или `422`."""
        if stored.get("fingerprint") != fingerprint:
            raise IdempotencyKeyReusedError()
        if stored.get("state") != "done":
            raise RequestInProgressError()
        app_logger.info("core.idempotency_replayed")
        raise IdempotentReplayError(
            status=int(stored["status"]),
            headers=dict(stored.get("headers", {})),
            body=base64.b64decode(stored["body"]),
        )


class IdempotencyMiddleware:
    """ASGI-middleware: сохраняет ответ запроса, захватившего `Idempotency-Key`."""

    def __init__(self, app: ASGIApp) -> None:
        """Оборачивает ASGI-приложение."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Перехватывает ответ и сохраняет его по захваченному ключу."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = 0
        headers: dict[str, str] = {}
        body = bytearray()

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                for raw_name, raw_value in message.get("headers", []):
                    name = raw_name.decode("latin-1").lower()
                    if name in _STORED_HEADERS:
                        headers[name] = raw_value.decode("latin-1")
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except BaseException:
            await _release(scope)
            raise
        claim = scope.get("state", {}).get(_STATE_KEY)
        if not isinstance(claim, IdempotencyClaim):
            return
        if status >= 500 or status == 0:
            await _release(scope)
            return
        record = {
            "state": "done",
            "fingerprint": claim.fingerprint,
            "status": status,
            "headers": headers,
            "body": base64.b64encode(bytes(body)).decode("ascii"),
        }
        try:
            await claim.redis.set_json(claim.key, record, ttl=RESPONSE_TTL)
        except RedisUnavailableError:
            app_logger.warning("core.idempotency_redis_unavailable")


async def _release(scope: Scope) -> None:
    """Снимает запись «в работе», чтобы повтор запроса выполнился заново."""
    claim = scope.get("state", {}).get(_STATE_KEY)
    if not isinstance(claim, IdempotencyClaim):
        return
    try:
        await claim.redis.delete(claim.key)
    except RedisUnavailableError:
        app_logger.warning("core.idempotency_redis_unavailable")
