"""Провайдер капчи за интерфейсом (OQ-10; SYS-10-R22).

`CaptchaProvider.verify(token, ip)` проверяет токен, полученный фронтендом от виджета капчи.
Реализации: `StubCaptchaProvider` (принимает только `captcha-ok`) и `YandexSmartCaptchaProvider`
(POST `/validate` с серверным ключом, `token`, `ip`; ответ `{"status": "ok" | "failed"}`). Сбой провайдера —
отказ (fail-closed) с предупреждением в лог; серверный ключ и токен в логи не попадают.
"""

from typing import Protocol, runtime_checkable

import httpx
from pydantic import SecretStr

from app.core.logging.context import get_logger
from configs.captcha_config import CaptchaSettings, captcha_settings


logger = get_logger("flt.core.captcha")

STUB_VALID_TOKEN = "captcha-ok"  # nosec B105 — публичный токен заглушки капчи (SYS-10-R22), не секрет


@runtime_checkable
class CaptchaProvider(Protocol):
    """Проверка токена капчи на сервере."""

    async def verify(self, token: str, ip: str) -> bool:
        """True — капча пройдена; False — токен неверный, пустой или провайдер недоступен."""
        ...


class StubCaptchaProvider:
    """Заглушка для local, CI и pytest: принимает только `captcha-ok` (SYS-10-R22)."""

    async def verify(self, token: str, ip: str) -> bool:
        """Сравнивает токен с `captcha-ok`."""
        return token == STUB_VALID_TOKEN


class YandexSmartCaptchaProvider:
    """Yandex SmartCaptcha: серверная проверка токена (провайдер в РФ, OQ-10)."""

    def __init__(self, server_key: SecretStr, *, validate_url: str, timeout_seconds: float) -> None:
        """Сохраняет серверный ключ, адрес проверки и таймаут."""
        self._server_key = server_key
        self._validate_url = validate_url
        self._timeout = timeout_seconds

    async def verify(self, token: str, ip: str) -> bool:
        """Проверяет токен у SmartCaptcha; любой сбой провайдера — отказ (fail-closed)."""
        if not token:
            return False
        form = {"secret": self._server_key.get_secret_value(), "token": token, "ip": ip}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._validate_url, data=form)
            response.raise_for_status()
            status = response.json().get("status")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            logger.warning("core.captcha_unavailable", error=type(exc).__name__)
            return False
        return bool(status == "ok")


def captcha_provider_from_settings(settings: CaptchaSettings = captcha_settings) -> CaptchaProvider:
    """Провайдер по `CAPTCHA_PROVIDER`: заглушка или Yandex SmartCaptcha."""
    if settings.CAPTCHA_PROVIDER == "yandex":
        return YandexSmartCaptchaProvider(
            settings.SMARTCAPTCHA_SERVER_KEY,
            validate_url=settings.CAPTCHA_VALIDATE_URL,
            timeout_seconds=settings.CAPTCHA_TIMEOUT_SECONDS,
        )
    return StubCaptchaProvider()
