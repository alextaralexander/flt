"""Почтовый ящик тестов: `MailClient`, который складывает письма в список вместо SMTP (SYS-10-R21)."""

from collections.abc import Mapping, Sequence

from app.core.mail import OutgoingMail, normalize_recipients


class InMemoryMailClient:
    """Реализация `MailClient` для фикстуры `mail_outbox`: письма — в `sent`, сеть не используется."""

    def __init__(self) -> None:
        """Пустой ящик."""
        self.sent: list[OutgoingMail] = []

    async def send(
        self,
        to: str | Sequence[str],
        subject: str,
        html: str,
        text: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Сохраняет письмо (с той же валидацией адресов и заголовков, что у SMTP-клиента)."""
        self.sent.append(OutgoingMail.create(normalize_recipients(to), subject, html, text, headers))
