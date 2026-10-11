"""Настройки капчи shared kernel (OQ-10; SYS-10-R22; ADR-013).

`CAPTCHA_ENABLED` включает требование капчи после мягкого лимита (решают модули `identity` и
`assessment`); `CAPTCHA_PROVIDER` выбирает реализацию: `stub` (local, CI, pytest — принимает только
`captcha-ok`) или `yandex` (Yandex SmartCaptcha). Серверный ключ — секрет `SMARTCAPTCHA_SERVER_KEY`
(имя — ADR-013, таблица 3.1).
"""

from typing import Literal, Self

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import current_stand, stand_env_file


load_dotenv(".env")

YANDEX_VALIDATE_URL = "https://smartcaptcha.yandexcloud.net/validate"


class CaptchaSettings(BaseSettings):
    """Капча (env → env-файл стенда)."""

    model_config = SettingsConfigDict(extra="ignore", env_file=stand_env_file())

    CAPTCHA_ENABLED: bool = Field(default=False, description="Требовать капчу после мягкого лимита (OQ-10).")
    CAPTCHA_PROVIDER: Literal["stub", "yandex"] = Field(
        default="stub", description="Провайдер: stub (тесты, local, CI) или yandex (Yandex SmartCaptcha)."
    )
    CAPTCHA_SITE_KEY: str = Field(default="", description="Клиентский ключ SmartCaptcha (не секрет, для фронтенда).")
    SMARTCAPTCHA_SERVER_KEY: SecretStr = Field(
        default=SecretStr(""), description="Серверный ключ Yandex SmartCaptcha (секрет, ADR-013)."
    )
    CAPTCHA_VALIDATE_URL: str = Field(default=YANDEX_VALIDATE_URL, description="Адрес проверки токена SmartCaptcha.")
    CAPTCHA_TIMEOUT_SECONDS: float = Field(default=3.0, description="Таймаут запроса проверки токена.")

    @model_validator(mode="after")
    def _provider_configured(self) -> Self:
        """Yandex требует серверного ключа; на prod включённая капча не может быть заглушкой."""
        if self.CAPTCHA_PROVIDER == "yandex" and not self.SMARTCAPTCHA_SERVER_KEY.get_secret_value():
            raise ValueError("CAPTCHA_PROVIDER=yandex требует SMARTCAPTCHA_SERVER_KEY (ADR-013).")
        if self.CAPTCHA_ENABLED and self.CAPTCHA_PROVIDER == "stub" and current_stand() == "prod":
            raise ValueError("На prod включённая капча не может использовать провайдер stub.")
        return self


captcha_settings = CaptchaSettings()
