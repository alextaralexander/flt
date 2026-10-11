"""Тесты провайдеров капчи: заглушка `stub` и Yandex SmartCaptcha за интерфейсом (OQ-10; SYS-10-R22).

Yandex SmartCaptcha в тестах не вызывается: HTTP подменяется `respx`.
"""

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError
from structlog.testing import capture_logs

from app.core.captcha import (
    CaptchaProvider,
    StubCaptchaProvider,
    YandexSmartCaptchaProvider,
    captcha_provider_from_settings,
)
from configs.captcha_config import CaptchaSettings


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R22")]

VALIDATE_URL = "https://smartcaptcha.yandexcloud.net/validate"
SERVER_KEY = "ysc2_test_server_key"  # pragma: allowlist secret


class TestStub:
    """Заглушка принимает только `captcha-ok`."""

    @pytest.mark.parametrize(("token", "expected"), [("captcha-ok", True), ("captcha-bad", False), ("", False)])
    async def test_verify(self, token: str, expected: bool) -> None:
        """`captcha-ok` — успех, любой другой токен — отказ."""
        provider: CaptchaProvider = StubCaptchaProvider()
        assert await provider.verify(token, "203.0.113.7") is expected


class TestYandexSmartCaptcha:
    """Проверка токена на сервере Yandex SmartCaptcha."""

    def _provider(self) -> YandexSmartCaptchaProvider:
        """Провайдер с тестовым серверным ключом."""
        return YandexSmartCaptchaProvider(SecretStr(SERVER_KEY), validate_url=VALIDATE_URL, timeout_seconds=1)

    @respx.mock
    async def test_ok(self) -> None:
        """Ответ `status: ok` — успех; в запросе — серверный ключ, токен и IP клиента."""
        # - Arrange -
        route = respx.post(VALIDATE_URL).mock(return_value=httpx.Response(200, json={"status": "ok", "message": ""}))

        # - Act -
        result = await self._provider().verify("user-token", "203.0.113.7")

        # - Assert -
        assert result is True
        sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
        assert sent == {"secret": SERVER_KEY, "token": "user-token", "ip": "203.0.113.7"}

    @respx.mock
    async def test_failed(self) -> None:
        """Ответ `status: failed` — отказ."""
        respx.post(VALIDATE_URL).mock(return_value=httpx.Response(200, json={"status": "failed", "message": "x"}))
        assert await self._provider().verify("user-token", "203.0.113.7") is False

    @respx.mock
    @pytest.mark.parametrize(
        "response",
        [httpx.Response(500, text="oops"), httpx.Response(200, text="not json"), httpx.ConnectError("down")],
    )
    async def test_provider_unavailable_fails_closed(self, response: httpx.Response | Exception) -> None:
        """Сбой провайдера — отказ (fail-closed) и предупреждение без ключа и токена в логе."""
        # - Arrange -
        route = respx.post(VALIDATE_URL)
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)

        # - Act -
        with capture_logs() as logs:
            result = await self._provider().verify("user-token", "203.0.113.7")

        # - Assert -
        assert result is False
        assert any(entry["event"] == "core.captcha_unavailable" for entry in logs)
        assert all(SERVER_KEY not in str(entry) and "user-token" not in str(entry) for entry in logs)

    async def test_empty_token_is_rejected_without_request(self) -> None:
        """Пустой токен отклоняется без обращения к провайдеру."""
        with respx.mock(assert_all_called=False) as router:
            route = router.post(VALIDATE_URL)
            assert await self._provider().verify("", "203.0.113.7") is False
            assert not route.called


class TestSettings:
    """Выбор провайдера конфигурацией (OQ-10)."""

    def test_stub_by_default(self) -> None:
        """По умолчанию капча выключена, провайдер — заглушка."""
        settings = CaptchaSettings(_env_file=None)
        assert settings.CAPTCHA_ENABLED is False
        assert isinstance(captcha_provider_from_settings(settings), StubCaptchaProvider)

    def test_yandex_requires_server_key(self) -> None:
        """Yandex без `SMARTCAPTCHA_SERVER_KEY` — ошибка старта; с ключом — провайдер Yandex."""
        with pytest.raises(ValidationError, match="SMARTCAPTCHA_SERVER_KEY"):
            CaptchaSettings(CAPTCHA_PROVIDER="yandex", _env_file=None)
        settings = CaptchaSettings(
            CAPTCHA_PROVIDER="yandex", SMARTCAPTCHA_SERVER_KEY=SecretStr(SERVER_KEY), _env_file=None
        )
        assert isinstance(captcha_provider_from_settings(settings), YandexSmartCaptchaProvider)

    def test_stub_is_forbidden_when_enabled_on_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """На prod включённая капча с заглушкой недопустима: `captcha-ok` прошёл бы проверку."""
        monkeypatch.setenv("STAND_NAME", "prod")
        with pytest.raises(ValidationError, match="stub"):
            CaptchaSettings(CAPTCHA_ENABLED=True, _env_file=None)
