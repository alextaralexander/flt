"""Единый SMTP-клиент shared kernel (OQ-11; SYS-01-R13).

`MailClient` — интерфейс отправки; `SmtpMailClient` — реализация на `aiosmtplib`. Модули получают
клиент из контейнера (`container.resolve(MailClient)`), тесты подменяют его фикстурой `mail_outbox`
(SYS-10-R21). Шаблоны и решение о доставке — модули-источники и `notifications`; ядро только отправляет.
Адреса получателей и тексты писем в логи не пишутся (ADR-010).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Protocol, Self, runtime_checkable

import aiosmtplib
from email_validator import EmailNotValidError, validate_email

from app.core.logging.context import get_logger
from configs.mail_config import MailSettings, mail_settings


logger = get_logger("flt.core.mail")


class MailDeliveryError(RuntimeError):
    """SMTP-сервер недоступен или отклонил письмо (без адресов и текста письма в сообщении)."""


def normalize_recipients(to: str | Sequence[str]) -> tuple[str, ...]:
    """Проверенные адреса получателей.

    Raises:
        ValueError: Получателей нет или адрес некорректен (в том числе с переводом строки).
    """
    recipients = (to,) if isinstance(to, str) else tuple(to)
    if not recipients:
        raise ValueError("Нет получателей письма.")
    for address in recipients:
        try:
            validate_email(address, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError("Некорректный адрес получателя.") from exc
    return recipients


def _check_header(name: str, value: str) -> None:
    """Запрет переводов строки в заголовках (header injection)."""
    if any(char in name or char in value for char in "\r\n"):
        raise ValueError(f"Заголовок {name.splitlines()[0]!r} содержит перевод строки.")


@dataclass(frozen=True)
class OutgoingMail:
    """Письмо к отправке: получатели, тема, HTML и текстовая версия, дополнительные заголовки."""

    to: tuple[str, ...]
    subject: str
    html: str
    text: str
    headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def create(cls, to: tuple[str, ...], subject: str, html: str, text: str, headers: Mapping[str, str] | None) -> Self:
        """Письмо с проверкой темы и заголовков на переводы строки."""
        _check_header("Subject", subject)
        extra = tuple((headers or {}).items())
        for name, value in extra:
            _check_header(name, value)
        return cls(to=to, subject=subject, html=html, text=text, headers=extra)

    def to_message(self, sender: str) -> EmailMessage:
        """MIME-письмо `multipart/alternative` (text/plain + text/html)."""
        message = EmailMessage()
        message["From"] = sender
        message["To"] = ", ".join(self.to)
        message["Subject"] = self.subject
        message["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].rpartition("@")[2] or None)
        for name, value in self.headers:
            message[name] = value
        message.set_content(self.text)
        message.add_alternative(self.html, subtype="html")
        return message


@runtime_checkable
class MailClient(Protocol):
    """Отправка транзакционных писем платформы."""

    async def send(
        self,
        to: str | Sequence[str],
        subject: str,
        html: str,
        text: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Отправляет письмо с HTML- и текстовой частью.

        Raises:
            ValueError: Некорректный адрес или перевод строки в заголовках.
            MailDeliveryError: Письмо не принято SMTP-сервером.
        """
        ...


class SmtpMailClient:
    """`MailClient` поверх SMTP (`aiosmtplib`): соединение на каждое письмо, без состояния между вызовами."""

    def __init__(self, settings: MailSettings) -> None:
        """Сохраняет неизменяемые настройки SMTP."""
        self._settings = settings

    @classmethod
    def from_settings(cls) -> SmtpMailClient:
        """Клиент с настройками процесса (`SMTP_*`)."""
        return cls(mail_settings)

    async def send(
        self,
        to: str | Sequence[str],
        subject: str,
        html: str,
        text: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Отправляет письмо по SMTP (см. `MailClient.send`)."""
        mail = OutgoingMail.create(normalize_recipients(to), subject, html, text, headers)
        config = self._settings
        try:
            await aiosmtplib.send(
                mail.to_message(config.SMTP_FROM),
                hostname=config.SMTP_HOST,
                port=config.SMTP_PORT,
                username=config.SMTP_USERNAME or None,
                password=config.SMTP_PASSWORD.get_secret_value() or None,
                use_tls=config.SMTP_SECURITY == "tls",
                start_tls=config.SMTP_SECURITY == "starttls",
                timeout=config.SMTP_TIMEOUT_SECONDS,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            logger.warning("core.mail_delivery_failed", error=type(exc).__name__, recipients=len(mail.to))
            raise MailDeliveryError(f"SMTP не принял письмо: {type(exc).__name__}.") from exc
        logger.info("core.mail_sent", recipients=len(mail.to))
