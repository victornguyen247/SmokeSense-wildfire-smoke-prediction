"""The one shape every outgoing email takes."""

from dataclasses import dataclass

# Every email must carry this line (API-07 / PM-06 §7). Templates and tests share it, so
# changing the copy is a one-line edit here.
EXPERIMENTAL_LINE = (
    "SmokeSense forecasts are experimental model estimates, not official warnings."
)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # Goes in the List-Unsubscribe headers (RFC 8058 one-click).
    unsubscribe_url: str
