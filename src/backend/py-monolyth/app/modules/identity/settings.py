"""Настройки модуля `identity` (ADR-002, раздел 3.3).

Префикс переменных — `IDENTITY_`, файл стенда — `envs/<стенд>/identity_<стенд>.env`.
Секреты — поля `SecretStr` без значения по умолчанию, только из переменных окружения (ADR-013).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file


class IdentitySettings(BaseSettings):
    """Настройки модуля `identity`."""

    model_config = SettingsConfigDict(
        env_prefix="IDENTITY_",
        env_file=stand_env_file("identity"),
        extra="ignore",
    )
