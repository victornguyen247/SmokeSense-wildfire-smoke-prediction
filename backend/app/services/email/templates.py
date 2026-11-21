"""Confirmation and alert emails: plain text plus HTML, from stdlib string templates.

Every template carries the experimental line; alert emails also carry an unsubscribe
link. Copy is owned by PM-06 §6; edit the files in templates/, not this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

from app.core.geo import LOW_CONFIDENCE_DIST_KM
from shared.aqi import AQI_CATEGORIES, aqi_category, truncate_pm25

from .message import EXPERIMENTAL_LINE, EmailMessage, EmailSendError

_DIR = Path(__file__).parent / "templates"
_LA = ZoneInfo("America/Los_Angeles")

# (horizon_hours, target_time, pm25) for each cut-off the episode hit.
AlertHorizon = tuple[int, datetime, float]


@lru_cache
def _template(name: str, ext: str) -> Template:
    return Template((_DIR / f"{name}.{ext}").read_text(encoding="utf-8"))


def _render(
    name: str,
    ext: str,
    values: dict[str, str],
    *,
    html: bool,
    raw_keys: frozenset[str] = frozenset(),
) -> str:
    # HTML output escapes every value, including URLs placed in attributes.
    # raw_keys are already escaped fragments (e.g. a built <ul>).
    clean = {
        k: (v if (not html or k in raw_keys) else escape(v, quote=True))
        for k, v in values.items()
    }
    return _template(name, ext).substitute(clean)


def _build(
    name: str,
    to: str,
    subject: str,
    unsubscribe_url: str,
    values: dict[str, str],
    *,
    raw_keys: frozenset[str] = frozenset(),
) -> EmailMessage:
    values = {**values, "experimental_line": EXPERIMENTAL_LINE, "unsubscribe_url": unsubscribe_url}
    return EmailMessage(
        to=to,
        subject=subject,
        text=_render(name, "txt", values, html=False),
        html=_render(name, "html", values, html=True, raw_keys=raw_keys),
        unsubscribe_url=unsubscribe_url,
    )


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_local(dt: datetime) -> str:
    """America/Los_Angeles like 'Sat, Jul 27, 5 PM PDT' (PM-06 §6)."""
    local = _as_utc(dt).astimezone(_LA)
    hour = local.hour % 12 or 12
    am_pm = "AM" if local.hour < 12 else "PM"
    return f"{local.strftime('%a, %b')} {local.day}, {hour} {am_pm} {local.tzname()}"


def _aqi_label(pm25: float) -> str:
    key = aqi_category(pm25)
    return next(c.label for c in AQI_CATEGORIES if c.key == key)


def _aqi_color(pm25: float) -> str:
    key = aqi_category(pm25)
    return next(c.color for c in AQI_CATEGORIES if c.key == key)


def _pm25_text(pm25: float) -> str:
    return f"{truncate_pm25(pm25):.1f}"


def _horizon_line(horizon_hours: int, target_time: datetime, pm25: float) -> str:
    return (
        f"In {horizon_hours} h, around {format_local(target_time)}: "
        f"{_pm25_text(pm25)} µg/m³ ({_aqi_label(pm25)})"
    )


def render_confirmation(
    *,
    to: str,
    place: str,
    confirm_url: str,
    unsubscribe_url: str,
    expires_at: datetime,
) -> EmailMessage:
    return _build(
        "confirmation",
        to,
        f"Confirm your SmokeSense smoke alerts for {place}",
        unsubscribe_url,
        {
            "place": place,
            "confirm_url": confirm_url,
            "expires_local": format_local(expires_at),
        },
    )


def render_alert(
    *,
    to: str,
    place: str,
    horizons: list[AlertHorizon],
    issued_at: datetime,
    map_url: str,
    nearest_monitor_dist_km: float,
    unsubscribe_url: str,
    low_confidence_dist_km: float = LOW_CONFIDENCE_DIST_KM,
) -> EmailMessage:
    if not horizons:
        raise EmailSendError("alert requires at least one horizon")

    ordered = sorted(horizons, key=lambda h: h[0])
    text_lines = "\n".join(
        f"  - {_horizon_line(hours, target, pm25)}" for hours, target, pm25 in ordered
    )
    html_items = [
        f"<li>In {hours} h, around {escape(format_local(target), quote=True)}: "
        f"{escape(_pm25_text(pm25), quote=True)} µg/m³ "
        f'(<span style="color:{_aqi_color(pm25)}">{escape(_aqi_label(pm25), quote=True)}</span>)</li>'
        for hours, target, pm25 in ordered
    ]
    html_lines = "<ul>\n" + "\n".join(html_items) + "\n</ul>"

    if nearest_monitor_dist_km > low_confidence_dist_km:
        dist = f"{nearest_monitor_dist_km:.1f}".rstrip("0").rstrip(".")
        confidence_text = (
            f"The nearest air monitor is {dist} km away, so this\n"
            f"forecast is lower confidence.\n\n"
        )
        confidence_html = (
            f"<p>The nearest air monitor is {escape(dist, quote=True)} km away, "
            f"so this forecast is lower confidence.</p>\n"
        )
    else:
        confidence_text = ""
        confidence_html = ""

    # Text and HTML templates use different keys for the dynamic blocks; unused
    # keys are fine for string.Template.
    return _build(
        "alert",
        to,
        f"Smoke alert for {place}: unhealthy for sensitive groups expected",
        unsubscribe_url,
        {
            "place": place,
            "issued_local": format_local(issued_at),
            "horizon_lines": text_lines,
            "horizon_lines_html": html_lines,
            "confidence_block": confidence_text,
            "confidence_block_html": confidence_html,
            "map_url": map_url,
        },
        raw_keys=frozenset({"horizon_lines_html", "confidence_block_html"}),
    )
