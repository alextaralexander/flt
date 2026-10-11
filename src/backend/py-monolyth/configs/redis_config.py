"""Настройки Redis (ADR-003, правило 9; ADR-013).

Режим `standalone` — один экземпляр (docker-compose), `sentinel` — мастер, реплика и
Sentinel (Kubernetes). Пароль — `SecretStr` из переменных окружения; пустой пароль
допустим только на стенде local, на остальных стендах его отсутствие — ошибка старта.
"""

from enum import StrEnum
from typing import Self

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import DEFAULT_STAND_NAME, current_stand, stand_env_file


load_dotenv(".env")


class RedisMode(StrEnum):
    """Режим подключения к Redis."""

    STANDALONE = "standalone"
    SENTINEL = "sentinel"


class RedisSettings(BaseSettings):
    """Настройки подключения к Redis (env → `envs/<stand>/redis_<stand>.env`)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file("redis"),
    )

    REDIS_MODE: RedisMode = Field(
        default=RedisMode.STANDALONE,
        description="Режим Redis: standalone (docker-compose) или sentinel (Kubernetes).",
    )
    REDIS_HOST: str = Field(
        default="127.0.0.1",
        description="Хост Redis в режиме standalone.",
    )
    REDIS_PORT: int = Field(
        default=6379,
        description="Порт Redis в режиме standalone.",
    )
    REDIS_SENTINEL_HOSTS: str = Field(
        default="",
        description="Адреса Sentinel через запятую (`host:port,host:port`) в режиме sentinel.",
    )
    REDIS_SENTINEL_MASTER: str = Field(
        default="flt",
        description="Имя мастера, за которым следят Sentinel.",
    )
    REDIS_DB: int = Field(
        default=0,
        description="Номер базы данных Redis.",
    )
    REDIS_PASSWORD: SecretStr = Field(
        default=SecretStr(""),
        description="Пароль Redis (`requirepass`); пустой допустим только на стенде local.",
    )
    REDIS_DECODE_RESPONSES: bool = Field(
        default=True,
        description="Декодировать ответы Redis из bytes в str.",
    )

    @model_validator(mode="after")
    def _check_mode_and_password(self) -> Self:
        """Пароль обязателен вне local; режим sentinel требует адресов Sentinel."""
        if current_stand() != DEFAULT_STAND_NAME and not self.REDIS_PASSWORD.get_secret_value():
            raise ValueError("REDIS_PASSWORD обязателен на стендах, кроме local (ADR-013).")
        if self.REDIS_MODE is RedisMode.SENTINEL and not self.sentinel_hosts:
            raise ValueError("REDIS_MODE=sentinel требует REDIS_SENTINEL_HOSTS (host:port через запятую).")
        return self

    @property
    def sentinel_hosts(self) -> list[tuple[str, int]]:
        """Адреса Sentinel как пары (host, port); порт по умолчанию — 26379."""
        hosts: list[tuple[str, int]] = []
        for item in self.REDIS_SENTINEL_HOSTS.split(","):
            address = item.strip()
            if not address:
                continue
            host, _, port = address.partition(":")
            hosts.append((host, int(port) if port else 26379))
        return hosts


redis_settings = RedisSettings()
