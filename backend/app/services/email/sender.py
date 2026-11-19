"""`send(message)`: the only way the rest of the app sends email."""

import logging

from app.core.config import get_settings

from .backends import EmailBackend, MemoryBackend, SmtpBackend
from .message import EmailMessage, EmailSendError

logger = logging.getLogger(__name__)

# One process-wide memory backend, so tests can read what `send` recorded.
memory_backend = MemoryBackend()


def get_backend() -> EmailBackend:
    settings = get_settings()
    if settings.email_backend == "memory":
        # Memory drops mail silently; it is for tests and local runs only.
        if settings.environment in ("staging", "production"):
            raise EmailSendError("EMAIL_BACKEND=memory is not allowed in staging or production")
        return memory_backend
    return SmtpBackend(settings.email_smtp_host, settings.email_smtp_port, settings.email_from)


def send_many(messages: list[EmailMessage]) -> None:
    """Deliver messages through the configured backend, one SMTP connection for all.

    Never logs the recipient or the body.
    """
    if not messages:
        return
    backend = get_backend()
    backend.deliver_many(messages)
    logger.info("sent %d email(s) via %s", len(messages), type(backend).__name__)


def send(message: EmailMessage) -> None:
    send_many([message])
