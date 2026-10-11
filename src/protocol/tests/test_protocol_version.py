"""Тесты заготовки пакета flt-protocol (ADR-008, этап 1 Г.1)."""

import importlib

import flt_protocol


def test_package_importable() -> None:
    """Пакет импортируется по имени модуля ``flt_protocol``."""
    module = importlib.import_module("flt_protocol")

    assert module is flt_protocol


def test_protocol_version_is_one() -> None:
    """Первая версия протокола агент ↔ платформа — 1 (ADR-008 §3.1)."""
    assert flt_protocol.PROTOCOL_VERSION == 1
    assert isinstance(flt_protocol.PROTOCOL_VERSION, int)


def test_public_api_exports_only_version() -> None:
    """До появления сообщений (этап 4) публичный API — только ``PROTOCOL_VERSION``."""
    assert flt_protocol.__all__ == ["PROTOCOL_VERSION"]
