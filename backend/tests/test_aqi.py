"""shared/aqi.py against the table in docs/api.md and the /meta fixture."""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from shared.aqi import (
    AQI_CATEGORIES,
    AQI_CATEGORY_LABEL,
    AQI_TABLE_VERSION,
    aqi_category,
    truncate_pm25,
)

META = json.loads((settings.api_contract_dir / "fixtures" / "meta.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("pm25", "category"),
    [
        (0.0, "good"),
        (9.0, "good"),
        (9.05, "good"),  # truncated, not rounded (docs/api.md)
        (9.1, "moderate"),
        (35.4, "moderate"),
        (35.46, "moderate"),
        (35.5, "unhealthy_sensitive"),
        (55.4, "unhealthy_sensitive"),
        (55.5, "unhealthy"),
        (125.4, "unhealthy"),
        (125.5, "very_unhealthy"),
        (225.4, "very_unhealthy"),
        (225.5, "hazardous"),
        (900.0, "hazardous"),
    ],
)
def test_category_breakpoints(pm25, category):
    assert aqi_category(pm25) == category


def test_truncates_without_float_error():
    assert truncate_pm25(35.4) == 35.4
    assert truncate_pm25(35.46) == 35.4
    assert truncate_pm25(0.0) == 0.0


def test_table_matches_what_meta_serves():
    assert [category._asdict() for category in AQI_CATEGORIES] == META["aqi_categories"]
    assert AQI_TABLE_VERSION == META["aqi_table_version"]
    assert AQI_CATEGORY_LABEL == META["aqi_category_label"]
