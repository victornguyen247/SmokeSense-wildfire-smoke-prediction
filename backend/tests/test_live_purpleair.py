"""DATA-06 live PurpleAir job: map layer only, EPA (Barkjohn) corrected, few billed fields."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from ingestion.live import purpleair
from ingestion.normalize import barkjohn_correct
from ml.feature_columns import EXCLUDED, FEATURES, FEATURES_V2

PAYLOAD = json.loads(
    (Path(__file__).parent / "fixtures/live/purpleair_sensors.json").read_text()
)
NOW = datetime(2026, 10, 24, 2, 40, tzinfo=timezone.utc)
KEY = "PURPLEAIR-LIVE-TEST-KEY-42"


def mock_client(payload=PAYLOAD, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(purpleair.settings, "purpleair_api_key", KEY)


def test_purpleair_is_not_a_model_feature():
    """Decision #12: PurpleAir is a map layer in v1, never a model input."""
    for columns in (FEATURES, FEATURES_V2):
        assert not [
            c for c in columns if "purple" in c.lower() or c.lower().startswith("pa_")
        ]
        assert not set(columns) & set(EXCLUDED)


def test_one_cheap_request_with_the_key_in_a_header():
    seen: list[httpx.Request] = []
    purpleair.fetch_records(mock_client(seen=seen), NOW)

    assert len(seen) == 1
    request = seen[0]
    assert request.url.path == "/v1/sensors"
    assert request.headers["x-api-key"] == KEY and KEY not in str(request.url)
    assert request.url.params["fields"].split(",") == list(purpleair.FIELDS)
    # Slow-moving metadata is not re-billed every run.
    assert {"name", "altitude", "date_created"}.isdisjoint(purpleair.FIELDS)
    assert (
        request.url.params["location_type"] == "0"
        and request.url.params["max_age"] == "3600"
    )


def test_readings_are_corrected_and_qa_flagged():
    fetched, records = purpleair.fetch_records(mock_client(), NOW)
    by_sensor = {r["monitor"]["external_id"]: r["observation"] for r in records}

    assert fetched == 5
    # 1003 has no channel reading and 1005 no location.
    assert set(by_sensor) == {"1001", "1002", "1004"}
    ok = by_sensor["1001"]
    assert ok["correction"] == "purpleair_barkjohn" and ok["qa_flag"] == "ok"
    assert ok["pm25"] == round(barkjohn_correct(21.0, 40), 2) == 13.31
    # Stored under the hour the reading falls in.
    assert ok["valid_at"] == datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)
    # No humidity: uncorrected, so never a label.
    assert by_sensor["1002"]["correction"] == "purpleair_raw"
    assert by_sensor["1004"]["qa_flag"] == "invalid"  # A/B channels disagree
    assert {r["monitor"]["source"] for r in records} == {"purpleair"}


def test_newer_reading_in_the_same_hour_replaces_it(live_db):
    first = purpleair.run(session_factory=live_db, client=mock_client(), now=NOW)
    again = purpleair.run(session_factory=live_db, client=mock_client(), now=NOW)
    newer = json.loads(json.dumps(PAYLOAD))
    newer["data"][0][5] = 40.0  # sensor 1001 channel A, later in the same hour
    later = purpleair.run(
        session_factory=live_db,
        client=mock_client(newer),
        now=NOW + timedelta(minutes=10),
    )

    assert first["status"] == "success"
    written = (first["rows_written"], again["rows_written"], later["rows_written"])
    assert written == (3, 0, 1)
    with live_db() as s:
        rows = s.execute(
            text(
                "select m.external_id, o.correction, o.ingestion_run_id from observations o "
                "join monitors m on m.id = o.monitor_id where m.source = 'purpleair'"
            )
        ).all()
    assert len(rows) == 3 and all(r.ingestion_run_id for r in rows)
