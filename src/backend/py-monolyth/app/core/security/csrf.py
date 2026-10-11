"""Signed double-submit CSRF-токен (ADR-006, раздел 3.4; OWASP CSRF Cheat Sheet).

Токен — `<random>.<hmac>`: `random` — 16 случайных байт base64url без выравнивания,
`hmac` — HMAC-SHA256(`AUTH_CSRF_SECRET`, `random || sid`) base64url без выравнивания, где `sid` —
каноническая строка UUID сессии. Выпускает токен модуль `identity` (cookie `__Host-flt_csrf` при
входе и refresh), проверяет — `get_current_user` для изменяющих методов cookie-клиента: заголовок
`X-CSRF-Token` равен cookie и подпись валидна для сессии токена доступа. Серверного состояния нет.
"""

import base64
import hashlib
import hmac
import secrets
from uuid import UUID


CSRF_COOKIE = "__Host-flt_csrf"
CSRF_HEADER = "X-CSRF-Token"
CSRF_RANDOM_BYTES = 16
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _b64(raw: bytes) -> str:
    """base64url без `=`."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signature(random_part: str, sid: UUID, secret: str) -> str:
    """HMAC-SHA256 от `random || sid`."""
    digest = hmac.new(secret.encode(), random_part.encode("ascii") + str(sid).encode("ascii"), hashlib.sha256)
    return _b64(digest.digest())


def issue_csrf_token(sid: UUID, secret: str) -> str:
    """Новый CSRF-токен, привязанный к сессии `sid`.

    Args:
        sid: Сессия (семейство refresh-токенов) из access-токена.
        secret: Значение `AUTH_CSRF_SECRET`.

    Returns:
        Строка `<random>.<hmac>` для cookie `__Host-flt_csrf`.
    """
    random_part = _b64(secrets.token_bytes(CSRF_RANDOM_BYTES))
    return f"{random_part}.{_signature(random_part, sid, secret)}"


def csrf_token_valid(token: str, sid: UUID, secret: str) -> bool:
    """Подпись токена валидна для сессии `sid` (сравнение за постоянное время)."""
    random_part, separator, signature = token.partition(".")
    if not separator or not random_part or not signature:
        return False
    try:
        expected = _signature(random_part, sid, secret)
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace"))
