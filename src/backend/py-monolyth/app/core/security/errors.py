"""Ошибки аутентификации и авторизации shared kernel (SYS-03-R7, R21, R22; ADR-006).

Классы — уточнения доменных ошибок HTTP-слоя `app.core.http.errors`, поэтому обработчик
`DomainError` отдаёт их в конверте `ErrorResponseV1` единообразно с остальными кодами `core.*`.
Коды — по таблице SYS-03-R7: `core.unauthenticated`, `core.forbidden`, `identity.csrf_invalid`.
Детали ответа не раскрывают ни токен, ни недостающие права.
"""

from typing import Any

from app.core.http.errors import ForbiddenError as HttpForbiddenError
from app.core.http.errors import UnauthenticatedError as HttpUnauthenticatedError


UNAUTHENTICATED_CODE = "core.unauthenticated"
FORBIDDEN_CODE = "core.forbidden"
CSRF_INVALID_CODE = "identity.csrf_invalid"


class UnauthenticatedError(HttpUnauthenticatedError):
    """401 `core.unauthenticated`: токена нет, он не прошёл проверку или сессия отозвана.

    Ответ содержит `WWW-Authenticate: Bearer` (наследуется от ошибки HTTP-слоя).

    Args:
        reason: Машиночитаемая причина (`missing_token`, `invalid_token`, `session_revoked`,
            `agent_token`, `origin_mismatch`); попадает в детали ответа, сам токен — никогда.
    """

    def __init__(self, reason: str = "invalid_token") -> None:
        """Формирует ошибку с причиной отказа без сведений о токене."""
        self.reason = reason
        super().__init__(f"Request is not authenticated: {reason}.", reason=reason)


class ForbiddenError(HttpForbiddenError):
    """403: у аутентифицированного пользователя нет права или объект вне области гранта (SYS-06-R5, R6).

    Args:
        code: Код ошибки; по умолчанию `core.forbidden`, провайдер ролей может уточнить его
            (`identity.email_not_verified` и т.п. — SYS-06-R7).
        **parameters: Детали ответа (перечень недостающих прав скрывается — SYS-03-R22).
    """

    def __init__(self, code: str = FORBIDDEN_CODE, **parameters: Any) -> None:
        """Формирует ошибку 403 с заданным кодом."""
        super().__init__(f"Access denied: {code}.", code=code, **parameters)


class CsrfInvalidError(ForbiddenError):
    """403 `identity.csrf_invalid`: cookie-клиент без валидного `X-CSRF-Token` (ADR-006, раздел 3.4)."""

    def __init__(self) -> None:
        """Формирует ошибку CSRF без подробностей проверки."""
        super().__init__(CSRF_INVALID_CODE)
