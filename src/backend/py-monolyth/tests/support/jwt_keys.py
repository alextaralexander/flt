"""Одноразовая Ed25519-пара ключей подписи JWT на сессию тестов (ADR-006 §3.3, ADR-013).

В тестах секретов нет: ключи генерируются при старте сессии и выставляются переменными
окружения в форматах ADR-006 — `JWT_SIGNING_KEYS` (`{"<kid>": "<PEM приватного ключа>"}`),
`JWT_ACTIVE_KID` и `JWT_PUBLIC_KEYS` (`{"<kid>": "<PEM публичного ключа>"}`). Проверку токенов
(`TokenVerifier`, Г.4) и выпуск (`TokenIssuer` модуля `identity`, Г.5) тесты получают с этой парой.
"""

import json
import secrets
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


JWT_ENV_NAMES = ("JWT_SIGNING_KEYS", "JWT_ACTIVE_KID", "JWT_PUBLIC_KEYS")


@dataclass(frozen=True)
class SigningKeyPair:
    """Пара ключей подписи с идентификатором `kid` (PEM-строки)."""

    kid: str
    private_pem: str
    public_pem: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> SigningKeyPair:
        """Активная пара из переменных окружения, установленных `install_session_key_pair`.

        Raises:
            KeyError: Переменные `JWT_*` не установлены.
        """
        kid = environ["JWT_ACTIVE_KID"]
        return cls(
            kid=kid,
            private_pem=json.loads(environ["JWT_SIGNING_KEYS"])[kid],
            public_pem=json.loads(environ["JWT_PUBLIC_KEYS"])[kid],
        )

    def environ(self) -> dict[str, str]:
        """Переменные окружения с этой парой в форматах ADR-006."""
        return {
            "JWT_SIGNING_KEYS": json.dumps({self.kid: self.private_pem}),
            "JWT_ACTIVE_KID": self.kid,
            "JWT_PUBLIC_KEYS": json.dumps({self.kid: self.public_pem}),
        }


def generate_signing_key_pair() -> SigningKeyPair:
    """Новая Ed25519-пара с уникальным `kid` вида `pytest-<hex>`."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return SigningKeyPair(kid=f"pytest-{secrets.token_hex(4)}", private_pem=private_pem, public_pem=public_pem)


def install_session_key_pair(environ: MutableMapping[str, str]) -> SigningKeyPair:
    """Генерирует пару и выставляет её в окружение (до импорта настроек приложения).

    Args:
        environ: Окружение процесса (`os.environ`).

    Returns:
        Установленная пара ключей.
    """
    pair = generate_signing_key_pair()
    environ.update(pair.environ())
    return pair
