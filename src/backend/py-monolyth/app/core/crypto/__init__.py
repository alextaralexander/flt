"""Криптография shared kernel: `SecretBox` (AES-256-GCM с версиями ключей, ADR-013, раздел 3.4)."""

from app.core.crypto.secret_box import DecryptionError, Sealed, SecretBox, UnknownKeyVersionError, uuid_aad


__all__ = ("DecryptionError", "Sealed", "SecretBox", "UnknownKeyVersionError", "uuid_aad")
