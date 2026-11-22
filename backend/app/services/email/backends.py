"""Delivery backends. `send` in `sender.py` picks one from EMAIL_BACKEND."""

import smtplib
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from .message import EmailMessage, EmailSendError


class EmailBackend(Protocol):
    def deliver_many(self, messages: list[EmailMessage]) -> None: ...


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

    def deliver_many(self, messages: list[EmailMessage]) -> None:
        """Send all messages over one connection."""
        try:
            mimes = [build_mime(m, self.sender) for m in messages]
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                for mime in mimes:
                    smtp.send_message(mime)
        except (OSError, ValueError, smtplib.SMTPException) as exc:
            # These errors can embed the recipient address, so report only the type.
            raise EmailSendError(f"SMTP delivery failed ({type(exc).__name__})") from None


class MemoryBackend:
    """Records messages instead of sending them. For tests."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def deliver_many(self, messages: list[EmailMessage]) -> None:
        self.outbox.extend(messages)
