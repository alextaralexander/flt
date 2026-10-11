"""Тесты `SecretBox`: AES-256-GCM, случайный nonce, AAD, версии ключей (ADR-013, раздел 3.4; SYS-08-R6)."""

import base64
import json
import os
from uuid import uuid4

import pytest

from app.core.crypto import DecryptionError, Sealed, SecretBox, UnknownKeyVersionError, uuid_aad


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-08-R6")]


def _key() -> bytes:
    """Случайный ключ 32 байта."""
    return os.urandom(32)


def _keys_json(**keys: bytes) -> str:
    """Значение `LLM_KEYS_ENCRYPTION_KEYS`: `{"v1": "<base64 32 байта>"}`."""
    return json.dumps({version: base64.b64encode(key).decode() for version, key in keys.items()})


class TestRoundTrip:
    """Шифрование и расшифровка с AAD."""

    def test_encrypt_and_decrypt(self) -> None:
        """Шифртекст не содержит открытого текста; расшифровка с тем же AAD возвращает его."""
        # - Arrange -
        box = SecretBox({"v1": _key()}, active_version="v1")
        aad = uuid_aad(uuid4(), uuid4())
        secret = b"sk-test-0123456789abcdef"  # pragma: allowlist secret

        # - Act -
        sealed = box.encrypt(secret, aad)

        # - Assert -
        assert sealed.key_version == "v1"
        assert len(sealed.nonce) == 12
        assert secret not in sealed.ciphertext
        assert box.decrypt(sealed, aad) == secret

    def test_text_plaintext(self) -> None:
        """Строка шифруется в UTF-8."""
        box = SecretBox({"v1": _key()}, active_version="v1")
        aad = uuid_aad(uuid4())
        assert box.decrypt(box.encrypt("ключ", aad), aad) == "ключ".encode()

    def test_nonce_is_random(self) -> None:
        """Каждое шифрование — новый nonce и новый шифртекст."""
        box = SecretBox({"v1": _key()}, active_version="v1")
        aad = uuid_aad(uuid4())
        first, second = box.encrypt(b"same", aad), box.encrypt(b"same", aad)
        assert first.nonce != second.nonce
        assert first.ciphertext != second.ciphertext

    def test_foreign_aad_fails(self) -> None:
        """Ключ нельзя переставить другому ученику: чужой AAD — `DecryptionError`."""
        # - Arrange -
        box = SecretBox({"v1": _key()}, active_version="v1")
        sealed = box.encrypt(b"secret", uuid_aad(uuid4(), uuid4()))

        # - Act / Assert -
        with pytest.raises(DecryptionError):
            box.decrypt(sealed, uuid_aad(uuid4(), uuid4()))

    def test_tampered_ciphertext_fails(self) -> None:
        """Изменённый шифртекст не проходит проверку тега GCM."""
        # - Arrange -
        box = SecretBox({"v1": _key()}, active_version="v1")
        aad = uuid_aad(uuid4())
        sealed = box.encrypt(b"secret", aad)
        tampered = Sealed(bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:], sealed.nonce, sealed.key_version)

        # - Act / Assert -
        with pytest.raises(DecryptionError):
            box.decrypt(tampered, aad)


class TestKeyVersions:
    """Ротация: новые записи — активной версией, старые читаются по своей `key_version`."""

    def test_rotation(self) -> None:
        """После добавления `v2` и переключения активной версии записи `v1` читаются, новые — `v2`."""
        # - Arrange -
        v1, v2 = _key(), _key()
        aad = uuid_aad(uuid4())
        old = SecretBox({"v1": v1}, active_version="v1").encrypt(b"old", aad)
        rotated = SecretBox({"v1": v1, "v2": v2}, active_version="v2")

        # - Act -
        new = rotated.encrypt(b"new", aad)

        # - Assert -
        assert rotated.decrypt(old, aad) == b"old"
        assert new.key_version == "v2"
        assert rotated.needs_reencryption(old)
        assert not rotated.needs_reencryption(new)

    def test_removed_version_fails(self) -> None:
        """Запись версии, которой нет в конфигурации, — `UnknownKeyVersionError`."""
        # - Arrange -
        aad = uuid_aad(uuid4())
        sealed = SecretBox({"v1": _key()}, active_version="v1").encrypt(b"x", aad)

        # - Act / Assert -
        with pytest.raises(UnknownKeyVersionError, match="v1"):
            SecretBox({"v2": _key()}, active_version="v2").decrypt(sealed, aad)

    def test_from_config(self) -> None:
        """Конфигурация в формате ADR-013: JSON версий с ключами base64 и активная версия."""
        # - Arrange -
        box = SecretBox.from_config(_keys_json(v1=_key(), v2=_key()), active_version="v2")
        aad = uuid_aad(uuid4())

        # - Act / Assert -
        assert box.encrypt(b"x", aad).key_version == "v2"
        assert box.versions == ("v1", "v2")

    @pytest.mark.parametrize(
        ("keys", "active", "message"),
        [
            ({"v1": b"short"}, "v1", "32"),
            ({"v1": os.urandom(32)}, "v2", "активн"),
            ({}, "v1", "активн"),
        ],
    )
    def test_invalid_configuration(self, keys: dict[str, bytes], active: str, message: str) -> None:
        """Ключ не 32 байта или активной версии нет — ошибка старта."""
        with pytest.raises(ValueError, match=message):
            SecretBox(keys, active_version=active)

    def test_malformed_config(self) -> None:
        """Некорректный JSON или base64 — ошибка без значения ключа в сообщении."""
        with pytest.raises(ValueError, match="JSON"):
            SecretBox.from_config("{oops", active_version="v1")
        with pytest.raises(ValueError, match="base64"):
            SecretBox.from_config(json.dumps({"v1": "***not-base64***"}), active_version="v1")

    def test_repr_hides_keys(self) -> None:
        """В `repr` нет материала ключей — только версии."""
        key = _key()
        box = SecretBox({"v1": key}, active_version="v1")
        assert base64.b64encode(key).decode() not in repr(box)
        assert key.hex() not in repr(box)
        assert "v1" in repr(box)
