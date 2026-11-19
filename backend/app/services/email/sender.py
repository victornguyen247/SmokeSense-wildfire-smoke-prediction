"""`send(message)`: the only way the rest of the app sends email."""

import logging

from app.core.config import get_settings

from .backends import EmailBackend, EmailSendError, MemoryBackend, SmtpBackend
from .message import EmailMessage

logger = logging.getLogger(__name__)

# One process-wide memory backend, so tests can read what `send` recorded.
memory_backend = MemoryBackend()


def get_backend() -> EmailBackend:
    settings = get_settings()
    name = settings.email_backend.strip().lower()
    if name == "memory":
        return memory_backend
    if name == "smtp":
        return SmtpBackend(settings.email_smtp_host, settings.email_smtp_port, settings.email_from)
    raise EmailSendError(f"Unknown EMAIL_BACKEND {name!r} (use smtp or memory)")


def send(message: EmailMessage) -> None:
    """Deliver one message through the configured backend.

    Never logs the recipient or the body.
    """
    backend = get_backend()
    backend.deliver(message)
    logger.info("email sent via %s", type(backend).__name__)
