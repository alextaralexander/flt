"""Ошибки аутентификации и авторизации shared kernel (SYS-03-R7, R21, R22; ADR-006).

Классы наследуют исключения `app.core.exceptions`, которые уже отображаются обработчиками
HTTP-слоя в конверт `ErrorResponseV1`: `InvalidTokenError` → 401, `InsufficientPermissionsError` → 403.
Коды ошибок — по таблице SYS-03-R7: `core.unauthenticated`, `core.forbidden`, `identity.csrf_invalid`.
Параметры ответа не раскрывают ни токен, ни недостающие права.
"""

from typing import Any

from app.core.exceptions import BaseCustomException, InsufficientPermissionsError, InvalidTokenError


UNAUTHENTICATED_CODE = "core.unauthenticated"
FORBIDDEN_CODE = "core.forbidden"
CSRF_INVALID_CODE = "identity.csrf_invalid"


class UnauthenticatedError(InvalidTokenError):
    """401 `core.unauthenticated`: токена нет, он не прошёл проверку или сессия отозвана.

    Args:
        reason: Машиночитаемая причина (`missing_token`, `invalid_token`, `session_revoked`,
            `agent_token`); попадает в параметры ответа, сам токен — никогда.
    """

    def __init__(self, reason: str = "invalid_token") -> None:
        """Формирует ошибку с причиной отказа без сведений о токене."""
        self.reason = reason
        self.description = "Occurs when the request has no valid access token or the session is revoked."
        BaseCustomException.__init__(
            self,
            message_mnemo_code=UNAUTHENTICATED_CODE,
            message=f"Request is not authenticated: {reason}.",
            reason=reason,
        )


class ForbiddenError(InsufficientPermissionsError):
    """403: у аутентифицированного пользователя нет права или объект вне области гранта (SYS-06-R5, R6).

    Args:
        code: Код ошибки; по умолчанию `core.forbidden`, провайдер ролей может уточнить его
            (`identity.email_not_verified` и т.п. — SYS-06-R7).
        **parameters: Параметры ответа (без перечня недостающих прав — SYS-03-R22).
    """

    def __init__(self, code: str = FORBIDDEN_CODE, **parameters: Any) -> None:
        """Формирует ошибку 403 с заданным кодом."""
        self.description = "Occurs when the user lacks the permission or the object is outside the grant scope."
        BaseCustomException.__init__(self, message_mnemo_code=code, message=f"Access denied: {code}.", **parameters)


class CsrfInvalidError(ForbiddenError):
    """403 `identity.csrf_invalid`: cookie-клиент без валидного `X-CSRF-Token` (ADR-006, раздел 3.4)."""

    def __init__(self) -> None:
        """Формирует ошибку CSRF без подробностей проверки."""
        super().__init__(CSRF_INVALID_CODE)
