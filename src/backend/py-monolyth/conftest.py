"""Корневой conftest: окружение тестовой сессии, нужное до импорта кода приложения.

pytest загружает этот файл раньше `tests/conftest.py`, который импортирует настройки и
собирает приложение. Здесь генерируется одноразовая Ed25519-пара ключей подписи JWT на
сессию тестов (ADR-006 §3.3, ADR-013): в тестах секретов нет, ключи живут только в окружении
процесса pytest. Фикстура `jwt_signing_keys` (`tests/conftest.py`) отдаёт эту пару тестам.
"""

import os

from tests.support.jwt_keys import install_session_key_pair


install_session_key_pair(os.environ)
