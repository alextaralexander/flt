"""Тесты SMTP-клиента shared kernel и фикстуры `mail_outbox` (OQ-11; SYS-10-R21).

Интеграционные тесты `SmtpMailClient` идут в SMTP-сервер теста на 127.0.0.1 (без внешней сети).
"""

from email import message_from_bytes, policy
from email.message import EmailMessage

import pytest
from pydantic import SecretStr, ValidationError

from app.core.container import container
from app.core.mail import MailClient, MailDeliveryError, SmtpMailClient
from configs.mail_config import MailSettings
from tests.support.mail import InMemoryMailClient
from tests.support.smtp_server import smtp_test_server


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R21")]


def _settings(port: int, **overrides: object) -> MailSettings:
    """Настройки SMTP тестового сервера."""
    fields: dict[str, object] = {
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": port,
        "SMTP_FROM": "FLT <noreply@flt.localhost>",
        "SMTP_TIMEOUT_SECONDS": 2,
        **overrides,
    }
    return MailSettings(**fields)  # type: ignore[arg-type]


class TestSmtpMailClient:
    """Отправка по SMTP: конверт, multipart text/html, заголовки."""

    async def test_message_is_delivered(self) -> None:
        """Письмо с текстовой и HTML-частью доходит до сервера с корректным конвертом и заголовками."""
        async with smtp_test_server() as server:
            # - Arrange -
            client = SmtpMailClient(_settings(server.port))

            # - Act -
            await client.send(
                ["learner@example.com", "second@example.com"],
                "Подтвердите email",
                "<p>Ссылка</p>",
                "Ссылка",
                headers={"X-FLT-Template": "identity.email_verify"},
            )

        # - Assert -
        [mail] = server.received
        assert mail.sender == "noreply@flt.localhost"
        assert mail.recipients == ["learner@example.com", "second@example.com"]
        message = message_from_bytes(mail.data, policy=policy.default)
        assert isinstance(message, EmailMessage)
        assert message["Subject"] == "Подтвердите email"
        assert message["From"] == "FLT <noreply@flt.localhost>"
        assert message["X-FLT-Template"] == "identity.email_verify"
        assert message["Message-ID"]
        plain, html = message.get_body(("plain",)), message.get_body(("html",))
        assert plain is not None and plain.get_content().strip() == "Ссылка"
        assert html is not None and "<p>Ссылка</p>" in html.get_content()

    async def test_unreachable_server_raises_delivery_error(self) -> None:
        """Недоступный SMTP — `MailDeliveryError` без адреса получателя в сообщении."""
        # - Arrange -
        async with smtp_test_server() as server:
            port = server.port
        client = SmtpMailClient(_settings(port))

        # - Act / Assert -
        with pytest.raises(MailDeliveryError) as exc_info:
            await client.send("learner@example.com", "s", "<p>h</p>", "t")
        assert "learner@example.com" not in str(exc_info.value)

    @pytest.mark.parametrize(
        ("to", "subject", "headers"),
        [
            ("learner@example.com", "Hi\r\nBcc: victim@example.com", None),
            ("learner@example.com", "Hi", {"X-Bad": "a\nBcc: victim@example.com"}),
            ("not-an-email", "Hi", None),
            ([], "Hi", None),
        ],
    )
    async def test_injection_and_bad_addresses_rejected(
        self, to: str | list[str], subject: str, headers: dict[str, str] | None
    ) -> None:
        """Перевод строки в заголовках (header injection) и неверный адрес — `ValueError` до отправки."""
        client = SmtpMailClient(_settings(1))
        with pytest.raises(ValueError):
            await client.send(to, subject, "<p>h</p>", "t", headers=headers)


class TestMailSettings:
    """Конфигурация SMTP (OQ-11): учётные данные — секрет из окружения."""

    def test_username_requires_password(self) -> None:
        """Логин без пароля — ошибка старта; Mailpit работает без учётных данных."""
        with pytest.raises(ValidationError, match="SMTP_PASSWORD"):
            _settings(25, SMTP_USERNAME="user")
        assert _settings(25, SMTP_USERNAME="user", SMTP_PASSWORD=SecretStr("pwd")).SMTP_USERNAME == "user"

    def test_password_is_not_in_repr(self) -> None:
        """Пароль — `SecretStr`, в `repr` настроек не попадает."""
        settings = _settings(25, SMTP_USERNAME="user", SMTP_PASSWORD=SecretStr("smtp-pass-value"))
        assert "smtp-pass-value" not in repr(settings)


async def test_mail_outbox_captures_mail_sent_via_container(mail_outbox: InMemoryMailClient) -> None:
    """`mail_outbox` подменяет `MailClient` в контейнере: код модуля отправляет, тест читает письма."""
    # - Act -
    await container.resolve(MailClient).send("learner@example.com", "Тема", "<b>html</b>", "text")

    # - Assert -
    [mail] = mail_outbox.sent
    assert (mail.to, mail.subject, mail.text) == (("learner@example.com",), "Тема", "text")
    assert isinstance(container.resolve(MailClient), InMemoryMailClient)
