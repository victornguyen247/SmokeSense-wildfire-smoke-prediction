"""Delivery backends. `send` in `sender.py` picks one from EMAIL_BACKEND."""

import smtplib
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from .message import EmailMessage


class EmailSendError(Exception):
    """Delivery failed. The message never contains the recipient or the body."""


class EmailBackend(Protocol):
    def deliver(self, message: EmailMessage) -> None: ...


def build_mime(message: EmailMessage, sender: str) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Date"] = formatdate(localtime=False)
    mime["Message-ID"] = make_msgid()
    mime["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
    mime["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    mime.set_content(message.text)
    mime.add_alternative(message.html, subtype="html")
    return mime


class SmtpBackend:
    """Plain SMTP, no auth or TLS: Mailpit locally and on staging. No real mail leaves."""

    def __init__(self, host: str, port: int, sender: str) -> None:
        self.host = host
        self.port = port
        self.sender = sender

    def deliver(self, message: EmailMessage) -> None:
        mime = build_mime(message, self.sender)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                smtp.send_message(mime)
        except (OSError, smtplib.SMTPException) as exc:
            # smtplib errors can embed the recipient address, so report only the type.
            raise EmailSendError(f"SMTP delivery failed ({type(exc).__name__})") from None


class MemoryBackend:
    """Records messages instead of sending them. For tests."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def deliver(self, message: EmailMessage) -> None:
        self.outbox.append(message)
