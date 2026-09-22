"""Настройки, нужные только тестам.

Вынесены из боевого `configs.settings.Settings`, чтобы тестовые поля
не жили в продовом классе настроек. Значения приходят из окружения
(pytest загружает `envs/.test.env` через env_files в pyproject.toml).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PytestSettings(BaseSettings):
    """Тестовые значения (имя класса не начинается с Test, чтобы pytest его не собирал)."""

    model_config = SettingsConfigDict(extra="ignore")

    TEST_MODE: bool = Field(
        default=False,
        description="Защита от запуска тестов на реальной БД.",
    )
    TEST_AUTH_TOKEN: str = Field(
        default="test-auth-token",
        description="Access token, подставляемый в тестовые запросы.",
    )
    TEST_USER_ID: str = Field(
        default="00000000-0000-0000-0000-000000000002",
        description="Идентификатор тестового пользователя.",
    )


test_settings = PytestSettings()
