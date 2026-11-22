"""The one shape every outgoing email takes."""

from dataclasses import dataclass
from urllib.parse import urlsplit

# Every email must carry this line (PM-06 §6). Templates and tests share it, so
# changing the copy is a one-line edit here.
EXPERIMENTAL_LINE = (
    "SmokeSense is a student forecast, not an official source. "
    "Check AirNow.gov and your local air district and public health agency."
)


class EmailSendError(Exception):
    """Building or delivering a message failed. Never contains the recipient or the body."""


def _no_line_breaks(value: str) -> bool:
    return "\r" not in value and "\n" not in value


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # Goes in the List-Unsubscribe headers (RFC 8058 one-click); http(s) only.
    unsubscribe_url: str

    def __post_init__(self) -> None:
        # Messages are rejected here, so a bad header can never reach a backend. The
        # error names the field, never its value (the recipient must not be logged).
        for name in ("to", "subject", "unsubscribe_url"):
            if not _no_line_breaks(getattr(self, name)):
                raise EmailSendError(f"{name} must not contain line breaks")
        parts = urlsplit(self.unsubscribe_url)
        if parts.scheme not in ("http", "https") or not parts.netloc or "<" in self.unsubscribe_url or ">" in self.unsubscribe_url:
            raise EmailSendError("unsubscribe_url must be an http(s) URL")
