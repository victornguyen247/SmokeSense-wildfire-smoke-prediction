"""EPA PM2.5 AQI categories: the one home for these thresholds (spec: docs/api.md).

`aqi_category` is computed at read time from an hourly value and never stored, so it is
an indicator, not an official 24 h / NowCast AQI. Values are truncated to 0.1 before the
breakpoints are applied, as EPA and AirNow do, and `pm25` is returned truncated too, so
the number and the color always agree.
"""

from __future__ import annotations

import math
from typing import NamedTuple

AQI_TABLE_VERSION = "epa-2024"


class AqiCategory(NamedTuple):
    key: str
    label: str
    color: str
    pm25_min: float
    pm25_max: float | None  # inclusive; None for the top category


AQI_CATEGORIES = (
    AqiCategory("good", "Good", "#00E400", 0.0, 9.0),
    AqiCategory("moderate", "Moderate", "#FFFF00", 9.1, 35.4),
    AqiCategory("unhealthy_sensitive", "Unhealthy for Sensitive Groups", "#FF7E00", 35.5, 55.4),
    AqiCategory("unhealthy", "Unhealthy", "#FF0000", 55.5, 125.4),
    AqiCategory("very_unhealthy", "Very Unhealthy", "#8F3F97", 125.5, 225.4),
    AqiCategory("hazardous", "Hazardous", "#7E0023", 225.5, None),
)


def truncate_pm25(pm25: float) -> float:
    """pm25 truncated to 0.1. The epsilon absorbs float error such as 35.4 * 10 = 353.99..."""
    return round(math.floor(pm25 * 10 + 1e-9) / 10, 1)


def aqi_category(pm25: float) -> str:
    """The category key for pm25, binned on its truncated value."""
    value = truncate_pm25(pm25)
    for category in AQI_CATEGORIES:
        if category.pm25_max is None or value <= category.pm25_max:
            return category.key
    raise AssertionError("the top category has no upper bound")
