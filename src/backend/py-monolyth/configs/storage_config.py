"""Настройки S3-совместимого хранилища файлов (ADR-007, раздел 3.11; ADR-013).

Класс создаётся лениво (`storage_settings()`), поэтому процесс, не работающий с файлами,
не требует ключей хранилища; ключи — секреты без значения по умолчанию.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file


class StorageSettings(BaseSettings):
    """Секция `storage` (env → `envs/<stand>/storage_<stand>.env`)."""

    model_config = SettingsConfigDict(extra="ignore", env_file=stand_env_file("storage"))

    S3_ENDPOINT_URL: str = Field(description="Внутренний адрес хранилища для операций монолита.")
    S3_PUBLIC_BASE_URL: str = Field(description="Адрес, который видит браузер (origin без пути), для подписи URL.")
    S3_REGION: str = Field(default="ru-1", description="Регион для SigV4.")
    S3_ACCESS_KEY: SecretStr = Field(description="Ключ доступа учётной записи `flt-backend`.")
    S3_SECRET_KEY: SecretStr = Field(description="Секретный ключ учётной записи `flt-backend`.")
    S3_PRESIGN_TTL_SECONDS: int = Field(default=900, description="TTL presigned GET.")
    S3_UPLOAD_TTL_SECONDS: int = Field(default=900, description="TTL presigned POST.")


def storage_settings() -> StorageSettings:
    """Настройки хранилища из окружения стенда (ошибка — нет обязательных переменных)."""
    return StorageSettings()
