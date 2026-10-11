"""Шифрование секретов пользователей AES-256-GCM с версиями ключей (ADR-013, раздел 3.4; SYS-08-R6).

Случайный nonce 12 байт на запись; AAD связывает шифртекст с владельцем (например
`user_id || connection_id`), поэтому запись нельзя переставить другому пользователю. В данных
хранятся `ciphertext`, `nonce`, `key_version`. Ротация: в конфигурацию добавляется новая версия,
затем она становится активной; старые записи читаются по своей версии и перешифровываются
фоновым заданием модуля-владельца (`needs_reencryption`).

Ключи передаёт конструктору модуль-владелец из своих настроек (`LLM_KEYS_ENCRYPTION_KEYS`,
`LLM_KEYS_ENCRYPTION_ACTIVE_VERSION` — модуль `llm_gateway`); ядро переменных не объявляет.
"""

import base64
import binascii
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


KEY_BYTES = 32
NONCE_BYTES = 12


class DecryptionError(ValueError):
    """Шифртекст не расшифровывается: чужой AAD, повреждение данных или неверный ключ."""


class UnknownKeyVersionError(KeyError):
    """Версии ключа записи нет в конфигурации (ключ удалён до перешифровки)."""


@dataclass(frozen=True)
class Sealed:
    """Зашифрованное значение для хранения: шифртекст с тегом GCM, nonce и версия ключа."""

    ciphertext: bytes
    nonce: bytes
    key_version: str


def uuid_aad(*ids: UUID) -> bytes:
    """AAD из идентификаторов: конкатенация 16-байтовых UUID (`user_id || connection_id`)."""
    return b"".join(identifier.bytes for identifier in ids)


class SecretBox:
    """AES-256-GCM с несколькими версиями ключей и одной активной версией для шифрования."""

    def __init__(self, keys: Mapping[str, bytes], *, active_version: str) -> None:
        """Проверяет ключи (32 байта) и наличие активной версии.

        Args:
            keys: Ключи по версиям (`{"v1": <32 байта>}`).
            active_version: Версия для новых записей.

        Raises:
            ValueError: Ключ не 32 байта или активной версии нет среди ключей.
        """
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ValueError(f"Ключ версии {version!r} должен быть {KEY_BYTES} байта (AES-256).")
        if active_version not in keys:
            raise ValueError(f"Нет ключа активной версии {active_version!r}.")
        self._ciphers = {version: AESGCM(key) for version, key in keys.items()}
        self._active_version = active_version

    @classmethod
    def from_config(cls, keys_json: str, *, active_version: str) -> SecretBox:
        """Ключи из конфигурации: JSON `{"v1": "<base64 32 байта>"}` и активная версия (ADR-013).

        Raises:
            ValueError: JSON или base64 некорректны (значения ключей в сообщение не попадают).
        """
        try:
            raw = json.loads(keys_json)
        except json.JSONDecodeError:
            raise ValueError('Ключи шифрования: ожидается JSON {"<версия>": "<base64>"}.') from None
        if not isinstance(raw, dict):
            raise ValueError('Ключи шифрования: ожидается JSON-объект {"<версия>": "<base64>"}.')
        keys: dict[str, bytes] = {}
        for version, encoded in raw.items():
            try:
                keys[str(version)] = base64.b64decode(str(encoded), validate=True)
            except binascii.Error, ValueError:
                raise ValueError(f"Ключ версии {version!r} не base64.") from None
        return cls(keys, active_version=active_version)

    @property
    def active_version(self) -> str:
        """Версия ключа для новых записей."""
        return self._active_version

    @property
    def versions(self) -> tuple[str, ...]:
        """Версии ключей в конфигурации (по возрастанию имени)."""
        return tuple(sorted(self._ciphers))

    def encrypt(self, plaintext: bytes | str, aad: bytes) -> Sealed:
        """Шифрует значение активным ключом со случайным nonce.

        Args:
            plaintext: Открытый текст (строка кодируется в UTF-8).
            aad: Связанные данные (`uuid_aad(user_id, connection_id)`), не хранятся в записи.
        """
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._ciphers[self._active_version].encrypt(nonce, data, aad)
        return Sealed(ciphertext=ciphertext, nonce=nonce, key_version=self._active_version)

    def decrypt(self, sealed: Sealed, aad: bytes) -> bytes:
        """Расшифровывает запись ключом её версии.

        Raises:
            UnknownKeyVersionError: Версии записи нет в конфигурации.
            DecryptionError: Неверный AAD или повреждённые данные.
        """
        cipher = self._ciphers.get(sealed.key_version)
        if cipher is None:
            raise UnknownKeyVersionError(f"Нет ключа версии {sealed.key_version!r}.")
        try:
            return cipher.decrypt(sealed.nonce, sealed.ciphertext, aad)
        except InvalidTag:
            raise DecryptionError("Шифртекст не прошёл проверку (AAD, данные или ключ).") from None

    def needs_reencryption(self, sealed: Sealed) -> bool:
        """Запись зашифрована не активной версией — её перешифрует фоновое задание при ротации."""
        return sealed.key_version != self._active_version

    def __repr__(self) -> str:
        """Представление без материала ключей."""
        return f"SecretBox(versions={self.versions}, active_version={self._active_version!r})"
