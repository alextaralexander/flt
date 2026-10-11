"""SMTP-клиент shared kernel (OQ-11): интерфейс `MailClient` и реализация `SmtpMailClient`."""

from app.core.mail.client import (
    MailClient,
    MailDeliveryError,
    OutgoingMail,
    SmtpMailClient,
    normalize_recipients,
)


__all__ = ("MailClient", "MailDeliveryError", "OutgoingMail", "SmtpMailClient", "normalize_recipients")
