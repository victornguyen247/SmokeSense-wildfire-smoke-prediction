"""DATA-06 freshness: per-source last_success_at in the /meta SourceFreshness shape."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from ingestion.live.freshness import (
    SOURCES,
    freshness_from_runs,
    source_freshness,
    stale_after_minutes,
)

NOW = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
SPEC = Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml"
THRESHOLDS = {"airnow": 150, "firms": 90, "nws_obs": 150}


@pytest.fixture(autouse=True)
def default_thresholds(monkeypatch):
    """No threshold overrides from the environment."""
    for name in THRESHOLDS:
        monkeypatch.delenv(
            f"FRESHNESS_STALE_AFTER_MINUTES_{name.upper()}", raising=False
        )


def source_freshness_schema() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(SPEC.read_text())["components"]["schemas"]["SourceFreshness"]


def check_shape(item: dict, schema: dict) -> None:
    assert set(item) == set(schema["required"]) == set(schema["properties"])
    assert item["source"] in schema["properties"]["source"]["enum"]
    for key in ("last_success_at", "latest_data_at"):
        value = item[key]
        assert value is None or (value.endswith("Z") and datetime.fromisoformat(value))
    assert item["age_minutes"] is None or (
        isinstance(item["age_minutes"], int) and item["age_minutes"] >= 0
    )
    assert isinstance(item["stale_after_minutes"], int) and isinstance(
        item["stale"], bool
    )


def test_shape_matches_the_meta_contract():
    schema = source_freshness_schema()
    items = freshness_from_runs(
        {"airdata": (NOW - timedelta(minutes=20), NOW - timedelta(minutes=80))},
        NOW,
        THRESHOLDS,
    )
    enum = schema["properties"]["source"]["enum"]
    assert [i["source"] for i in items] == [s for s in enum if s in SOURCES]
    for item in items:
        check_shape(item, schema)


def test_values_and_stale_rule():
    items = {
        i["source"]: i
        for i in freshness_from_runs(
            {
                "airdata": (NOW - timedelta(minutes=20), NOW - timedelta(minutes=80)),
                "firms": (NOW - timedelta(minutes=95), None),  # healthy job, no fires
            },
            NOW,
            THRESHOLDS,
        )
    }
    assert items["airnow"] == {
        "source": "airnow",
        "last_success_at": "2026-10-24T02:40:00Z",
        "latest_data_at": "2026-10-24T01:40:00Z",
        "age_minutes": 80,
        "stale_after_minutes": 150,
        "stale": False,
    }
    assert items["firms"]["stale"] is True and items["firms"]["age_minutes"] is None
    assert (
        items["nws_obs"]["last_success_at"] is None
        and items["nws_obs"]["stale"] is True
    )


def test_from_ingestion_runs_ignores_failures(live_db):
    with live_db() as s:
        s.execute(
            text("""
            insert into ingestion_runs (id, source, started_at, finished_at, status, watermark)
            values ('a', 'airdata', :t1, :t1, 'success', :w1),
                   ('b', 'airdata', :t2, :t2, 'failed', null),
                   ('c', 'nws_obs', :t1, :t1, 'partial', :w1)
        """),
            {
                "t1": NOW - timedelta(minutes=30),
                "t2": NOW - timedelta(minutes=5),
                "w1": NOW - timedelta(minutes=60),
            },
        )
        s.commit()
        items = {i["source"]: i for i in source_freshness(s, now=NOW)}

    assert set(items) == set(SOURCES)
    # The newest successful run, not the later failed one.
    assert items["airnow"]["last_success_at"] == "2026-10-24T02:30:00Z"
    assert items["nws_obs"]["age_minutes"] == 60 and items["nws_obs"]["stale"] is False
    schema = source_freshness_schema()
    for item in items.values():
        check_shape(item, schema)


def test_default_thresholds_are_about_two_missed_runs():
    assert stale_after_minutes() == THRESHOLDS


def test_purpleair_has_no_live_job_and_is_not_reported(live_db):
    """Meta.sources sets no minimum, so a source with no live job is left out, not stale."""
    items = freshness_from_runs({}, NOW, stale_after_minutes())
    assert [i["source"] for i in items] == ["airnow", "firms", "nws_obs"]
    with live_db() as s:
        assert "purpleair" not in {i["source"] for i in source_freshness(s, now=NOW)}


def test_meta_sources_allows_omitting_a_source():
    yaml = pytest.importorskip("yaml")
    meta = yaml.safe_load(SPEC.read_text())["components"]["schemas"]["Meta"]
    sources = meta["properties"]["sources"]
    assert sources["type"] == "array"
    assert "minItems" not in sources and "contains" not in sources


def test_thresholds_are_configurable(monkeypatch, live_db):
    monkeypatch.setenv("FRESHNESS_STALE_AFTER_MINUTES_FIRMS", "15")
    with live_db() as s:
        items = {i["source"]: i for i in source_freshness(s, now=NOW)}
    assert items["firms"]["stale_after_minutes"] == 15
