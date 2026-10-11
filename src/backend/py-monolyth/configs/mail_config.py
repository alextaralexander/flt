"""Настройки SMTP-клиента shared kernel (OQ-11; спецификация `shared_kernel`, раздел 8; ADR-013).

На local, dev, test и в CI письма принимает Mailpit (порт 1025, без учётных данных); в продуктиве —
российский транзакционный сервис. Пароль — секрет из переменных окружения (`SMTP_PASSWORD`).
"""

from typing import Literal, Self

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file


load_dotenv(".env")


class MailSettings(BaseSettings):
    """Подключение к SMTP (env → env-файл стенда)."""

    model_config = SettingsConfigDict(extra="ignore", env_file=stand_env_file())

    SMTP_HOST: str = Field(default="127.0.0.1", description="Хост SMTP (Mailpit на local, dev, test).")
    SMTP_PORT: int = Field(default=1025, description="Порт SMTP.")
    SMTP_USERNAME: str = Field(default="", description="Логин SMTP; пусто — без аутентификации (Mailpit).")
    SMTP_PASSWORD: SecretStr = Field(
        default=SecretStr(""),
        description="Пароль SMTP (секрет, ADR-013); обязателен, если задан SMTP_USERNAME.",
    )
    SMTP_FROM: str = Field(default="FLT <noreply@flt.localhost>", description="Отправитель писем платформы.")
    SMTP_SECURITY: Literal["none", "starttls", "tls"] = Field(
        default="none",
        description="Шифрование соединения: none (Mailpit), starttls (587) или tls (465).",
    )
    SMTP_TIMEOUT_SECONDS: float = Field(default=10.0, description="Таймаут соединения и команд SMTP.")

    @model_validator(mode="after")
    def _credentials_complete(self) -> Self:
        """Логин без пароля — ошибка конфигурации (секрет не передан окружением)."""
        if self.SMTP_USERNAME and not self.SMTP_PASSWORD.get_secret_value():
            raise ValueError("SMTP_PASSWORD обязателен, если задан SMTP_USERNAME (ADR-013).")
        return self


mail_settings = MailSettings()
