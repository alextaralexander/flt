"""Капча shared kernel (OQ-10): интерфейс `CaptchaProvider`, заглушка и Yandex SmartCaptcha."""

from app.core.captcha.provider import (
    STUB_VALID_TOKEN,
    CaptchaProvider,
    StubCaptchaProvider,
    YandexSmartCaptchaProvider,
    captcha_provider_from_settings,
)


__all__ = (
    "STUB_VALID_TOKEN",
    "CaptchaProvider",
    "StubCaptchaProvider",
    "YandexSmartCaptchaProvider",
    "captcha_provider_from_settings",
)
