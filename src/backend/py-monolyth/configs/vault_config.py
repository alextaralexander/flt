"""Чтение секретов из Vault.

Секрет читается один раз за процесс (`@lru_cache`) при первом обращении —
обычно при инициализации `configs.settings.Settings`, когда значение
не задано переменной окружения. Если Vault не сконфигурирован, работаем
только на env-переменных и явно сообщаем об этом в лог.
"""

from functools import lru_cache
from typing import Any

import structlog
from dotenv import load_dotenv
from hvac import Client
from pydantic import Field
from pydantic_core import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file


load_dotenv(".env")

# Логгер бутстрапа: объявлен здесь напрямую (а не импортом `app.core.logging.app_logger`),
# т.к. `vault_config` читается на этапе инициализации `Settings`, когда импорт слоя `app`
# создал бы циклический импорт. Имя `app` совпадает с общим логгером приложения.
logger = structlog.stdlib.get_logger("app")

_MISSING = object()


class VaultSettings(BaseSettings):
    """Параметры подключения к Vault (сам секрет читает `vault_secrets`)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file("vault"),
    )

    VAULT_TOKEN: str = Field(
        description="Токен доступа к Vault; берётся только из переменных окружения, не из env-файла стенда.",
    )
    VAULT_URL: str = Field(
        description="URL сервера Vault.",
    )
    VAULT_PATH: str = Field(
        description="Путь к секрету внутри Vault (kv v1).",
    )
    VAULT_MOUNT_POINT: str = Field(
        description="Mount point kv-хранилища Vault.",
    )


@lru_cache(maxsize=1)
def vault_secrets() -> dict[str, Any]:
    """Содержимое Vault-секрета (kv v1); пустой dict, если Vault не сконфигурирован.

    Синхронный HTTP-вызов — выполняется один раз при старте процесса,
    не вызывать из горячего пути обработчиков.

    Raises:
        RuntimeError: Vault сконфигурирован, но секрет прочитать не удалось.
    """
    try:
        config = VaultSettings()
    except ValidationError as exc:
        missing = ", ".join(str(error["loc"][0]) for error in exc.errors())
        logger.warning("Vault не сконфигурирован — секреты берутся только из env.", missing_fields=missing)
        return {}

    client = Client(url=config.VAULT_URL, token=config.VAULT_TOKEN)
    try:
        response = client.secrets.kv.v1.read_secret(path=config.VAULT_PATH, mount_point=config.VAULT_MOUNT_POINT)
    except Exception as exc:
        raise RuntimeError(f"Vault сконфигурирован ({config.VAULT_URL}), но чтение секрета не удалось: {exc}") from exc
    secret_data: dict[str, Any] = response["data"]["data"]
    return secret_data


def vault_secret(key: str) -> str:
    """Обязательное значение `key` из Vault-секрета; используется как default_factory в Settings.

    Raises:
        RuntimeError: ключа нет в Vault — подсказывает задать одноимённую переменную окружения.
    """
    value = vault_secrets().get(key, _MISSING)
    if value is _MISSING:
        raise RuntimeError(
            f"Секрет `{key}` не найден: задай переменную окружения {key} или добавь ключ в Vault-секрет."
        )
    return str(value)


def vault_secret_or(key: str, default: str) -> str:
    """Значение `key` из Vault-секрета; при отсутствии возвращает `default`."""
    value = vault_secrets().get(key, _MISSING)
    if value is _MISSING:
        return default
    return str(value)


def vault_secret_or_none(key: str) -> str | None:
    """Значение `key` из Vault-секрета; при отсутствии — None (для опциональных полей)."""
    value = vault_secrets().get(key, _MISSING)
    if value is _MISSING:
        return None
    return str(value)
