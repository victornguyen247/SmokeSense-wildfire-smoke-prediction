"""Confirmation and alert emails: plain text plus HTML, from stdlib string templates.

Every template carries the experimental line and an unsubscribe link. Copy is owned by
PM-06 §7; edit the files in templates/, not this module.
"""

from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template

from shared.aqi import AQI_CATEGORIES, aqi_category

from .message import EXPERIMENTAL_LINE, EmailMessage

_DIR = Path(__file__).parent / "templates"


@lru_cache
def _template(name: str, ext: str) -> Template:
    return Template((_DIR / f"{name}.{ext}").read_text(encoding="utf-8"))


def _render(name: str, ext: str, values: dict[str, str], *, html: bool) -> str:
    # HTML output escapes every value, including URLs placed in attributes.
    clean = {k: escape(v, quote=True) if html else v for k, v in values.items()}
    return _template(name, ext).substitute(clean)


def _build(name: str, to: str, subject: str, unsubscribe_url: str, values: dict[str, str]) -> EmailMessage:
    values = {**values, "experimental_line": EXPERIMENTAL_LINE, "unsubscribe_url": unsubscribe_url}
    return EmailMessage(
        to=to,
        subject=subject,
        text=_render(name, "txt", values, html=False),
        html=_render(name, "html", values, html=True),
        unsubscribe_url=unsubscribe_url,
    )


def render_confirmation(*, to: str, location: str, confirm_url: str, unsubscribe_url: str) -> EmailMessage:
    return _build(
        "confirmation", to, "Confirm your SmokeSense alerts", unsubscribe_url,
        {"location": location, "confirm_url": confirm_url},
    )


def render_alert(
    *,
    to: str,
    location: str,
    horizon_hours: int,
    pm25: float,
    valid_time_utc: str,
    unsubscribe_url: str,
) -> EmailMessage:
    # The category comes from the one AQI table, so emails agree with the API.
    key = aqi_category(pm25)
    category = next(c.label for c in AQI_CATEGORIES if c.key == key)
    return _build(
        "alert", to, f"Smoke alert for {location}: {category}", unsubscribe_url,
        {
            "location": location,
            "category": category,
            "horizon_hours": str(horizon_hours),
            "pm25": f"{pm25:.1f}",
            "valid_time_utc": valid_time_utc,
        },
    )
