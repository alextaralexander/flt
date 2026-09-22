"""Настройки Redis (стендовые env-файлы + Vault для кредов)."""

from functools import partial

from dotenv import load_dotenv
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file
from configs.vault_config import vault_secret_or


load_dotenv(".env")


class RedisSettings(BaseSettings):
    """Основные настройки Redis (креды — из env или Vault)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file("redis"),
    )

    REDIS_HOST: str = Field(
        default="127.0.0.1",
        description="Хост Redis.",
    )
    REDIS_PORT: int = Field(
        default=6379,
        description="Порт Redis.",
    )
    REDIS_DB: int = Field(
        default=0,
        description="Номер базы данных Redis.",
    )
    REDIS_USERNAME: str = Field(
        default_factory=partial(vault_secret_or, "REDIS_USERNAME", ""),
        description="Имя пользователя Redis (по умолчанию читается из Vault, иначе пусто).",
    )
    REDIS_PASSWORD: str = Field(
        default_factory=partial(vault_secret_or, "REDIS_PASSWORD", ""),
        description="Пароль пользователя Redis (по умолчанию читается из Vault, иначе пусто).",
    )
    REDIS_DECODE_RESPONSES: bool = Field(
        default=True,
        description="Декодировать ответы Redis из bytes в str.",
    )


class RedisSettingsStub(BaseSettings):
    """Резервные настройки Redis: локальный инстанс без кредов."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file("redis"),
    )

    REDIS_HOST: str = Field(
        default="127.0.0.1",
        description="Хост Redis.",
    )
    REDIS_PORT: int = Field(
        default=6379,
        description="Порт Redis.",
    )
    REDIS_DB: int = Field(
        default=0,
        description="Номер базы данных Redis.",
    )
    REDIS_USERNAME: str = Field(
        default="",
        description="Имя пользователя Redis (в стабе пусто — локальный инстанс без кредов).",
    )
    REDIS_PASSWORD: str = Field(
        default="",
        description="Пароль пользователя Redis (в стабе пусто — локальный инстанс без кредов).",
    )
    REDIS_DECODE_RESPONSES: bool = Field(
        default=True,
        description="Декодировать ответы Redis из bytes в str.",
    )


redis_settings: RedisSettings | RedisSettingsStub
try:
    redis_settings = RedisSettings()
except ValidationError:
    redis_settings = RedisSettingsStub()
