"""Хэширование паролей argon2id (ADR-006, раздел 3.1)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Хэш argon2id с параметрами по умолчанию `argon2-cffi` (RFC 9106, профиль с низкой памятью)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Пароль соответствует хэшу."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError, InvalidHashError:
        return False
